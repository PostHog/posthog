import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { teamLogic } from '~/scenes/teamLogic'
import { initKeaTests } from '~/test/init'
import { TeamType } from '~/types'

import { aiAllChannelsForFeatureFlags, supportSettingsLogic } from './supportSettingsLogic'

const PLAYBOOK_GET = {
    inherited_instructions: 'Default playbook.',
    custom_instructions: null,
    is_customized: false,
    default_version: 1,
    posthog_overlay_version: null,
    docs_source: null,
    max_chars: 8000,
}

describe('supportSettingsLogic', () => {
    let logic: ReturnType<typeof supportSettingsLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/conversations/v1/email/status': { configs: [] },
                '/api/projects/:team_id/conversations/ai_reply_playbook/': PLAYBOOK_GET,
            },
            post: {
                '/api/environments/:team_id/': async ({ request }) => [200, await request.json()],
                '/api/conversations/v1/teams/select-channel': { ok: true, teams_channels: [] },
                '/api/conversations/v1/teams/install': { ok: true, status: 'installed' },
                '/api/conversations/v1/teams/channels': { channels: [] },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    describe('aiAllChannelsForFeatureFlags', () => {
        it.each([
            ['no flags enabled', {}, ['widget', 'email', 'slack']],
            [
                'teams and github enabled',
                {
                    [FEATURE_FLAGS.PRODUCT_SUPPORT_TEAMS_ENABLED]: true,
                    [FEATURE_FLAGS.PRODUCT_SUPPORT_GITHUB_CHANNEL]: true,
                },
                ['widget', 'email', 'slack', 'teams', 'github'],
            ],
        ])('%s', (_label, flags, expected) => {
            expect(aiAllChannelsForFeatureFlags(flags)).toEqual(expected)
        })
    })

    describe('connectEmail', () => {
        let errorToastSpy: jest.SpyInstance

        beforeEach(() => {
            errorToastSpy = jest.spyOn(lemonToast, 'error').mockImplementation((() => '') as any)
        })

        afterEach(() => {
            errorToastSpy.mockRestore()
        })

        it.each([
            [
                'endpoint error',
                { error: 'The domain is already registered with another Mailgun account.' },
                'The domain is already registered with another Mailgun account.',
            ],
            ['validation error', { detail: 'Enter a valid email address.' }, 'Enter a valid email address.'],
        ])('shows the backend reason for an %s', async (_label, body, expectedMessage) => {
            useMocks({
                get: {
                    '/api/conversations/v1/email/status': { configs: [] },
                    '/api/projects/:team_id/conversations/ai_reply_playbook/': PLAYBOOK_GET,
                },
                post: {
                    '/api/conversations/v1/email/connect': () => [400, body],
                },
            })
            logic = supportSettingsLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            logic.actions.setNewEmailFromEmail('help@example.com')
            logic.actions.setNewEmailFromName('Example Support')

            logic.actions.connectEmail()
            await expectLogic(logic).toFinishAllListeners()

            expect(errorToastSpy).toHaveBeenCalledWith(expectedMessage)
        })
    })

    describe('default email channel', () => {
        const configs = [
            { id: 'a', from_email: 'a@x.com', domain_verified: true, is_default: true },
            { id: 'b', from_email: 'b@x.com', domain_verified: true, is_default: false },
        ] as any[]

        it('moves the primary flag to exactly one channel on setDefaultEmailDone', async () => {
            logic = supportSettingsLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners() // let the afterMount load settle first
            logic.actions.loadEmailConfigsDone(configs)
            logic.actions.setDefaultEmailDone('b')

            expect(logic.values.emailConfigs.filter((c) => c.is_default).map((c) => c.id)).toEqual(['b'])
        })

        it('promotes a replacement when the primary is disconnected', async () => {
            logic = supportSettingsLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            logic.actions.loadEmailConfigsDone(configs)
            logic.actions.disconnectEmailDone('a')

            expect(logic.values.emailConfigs.map((c) => ({ id: c.id, is_default: c.is_default }))).toEqual([
                { id: 'b', is_default: true },
            ])
        })
    })

    describe('aiResolutionChannels selector', () => {
        it('drops flag-gated channels that are no longer available', async () => {
            initKeaTests(true, {
                conversations_settings: {
                    slack_enabled: true,
                    teams_enabled: true,
                    ai_resolution_channels: ['widget', 'slack', 'teams'],
                },
            } as unknown as TeamType)
            featureFlagLogic.mount()

            logic = supportSettingsLogic()
            logic.mount()

            await expectLogic(logic).toMatchValues({
                aiAllChannels: ['widget', 'email', 'slack'],
                aiResolutionChannels: ['widget', 'slack'],
            })
        })
    })

    describe('slackNeedsReconnect selector', () => {
        it.each([
            ['slack not connected', { slack_enabled: false }, false],
            ['install predates scope tracking', { slack_enabled: true }, true],
            ['install missing files:write', { slack_enabled: true, slack_scopes: ['chat:write', 'files:read'] }, true],
            [
                'install has both file scopes',
                { slack_enabled: true, slack_scopes: ['chat:write', 'files:read', 'files:write'] },
                false,
            ],
        ])('%s', async (_label, settings, expected) => {
            initKeaTests(true, { conversations_settings: settings } as unknown as TeamType)
            logic = supportSettingsLogic()
            logic.mount()
            await expectLogic(logic).toMatchValues({ slackNeedsReconnect: expected })
        })
    })

    describe('aiSuggestionsEnabled selector', () => {
        it.each([
            ['conversations_settings is undefined', undefined, false],
            ['ai_suggestions_enabled is not set', { widget_enabled: true }, false],
            ['ai_suggestions_enabled is true', { ai_suggestions_enabled: true }, true],
        ])('%s', async (_label, settings, expected) => {
            if (settings) {
                initKeaTests(true, { conversations_settings: settings } as unknown as TeamType)
            }
            logic = supportSettingsLogic()
            logic.mount()
            await expectLogic(logic).toMatchValues({ aiSuggestionsEnabled: expected })
        })
    })

    describe('setAiSuggestionsEnabled', () => {
        it('sets loading state and dispatches updateCurrentTeam', async () => {
            logic = supportSettingsLogic()
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.setAiSuggestionsEnabled(true)
            })
                .toDispatchActions(['setAiSuggestionsLoading', 'updateCurrentTeam'])
                .toMatchValues({ aiSuggestionsLoading: true })
        })

        it('clears loading state on updateCurrentTeamSuccess', async () => {
            logic = supportSettingsLogic()
            logic.mount()

            logic.actions.setAiSuggestionsLoading(true)
            expect(logic.values.aiSuggestionsLoading).toBe(true)

            logic.actions.updateCurrentTeamSuccess({} as TeamType)
            expect(logic.values.aiSuggestionsLoading).toBe(false)
        })

        it('clears loading state on updateCurrentTeamFailure', async () => {
            logic = supportSettingsLogic()
            logic.mount()

            logic.actions.setAiSuggestionsLoading(true)
            expect(logic.values.aiSuggestionsLoading).toBe(true)

            logic.actions.updateCurrentTeamFailure('update failed')
            expect(logic.values.aiSuggestionsLoading).toBe(false)
        })
    })

    describe('aiDiagnosticsEnabled selector', () => {
        it.each([
            ['conversations_settings is undefined', undefined, false],
            ['ai_diagnostics_enabled is not set', { widget_enabled: true }, false],
            ['ai_diagnostics_enabled is true', { ai_diagnostics_enabled: true }, true],
        ])('%s', async (_label, settings, expected) => {
            if (settings) {
                initKeaTests(true, { conversations_settings: settings } as unknown as TeamType)
            }
            logic = supportSettingsLogic()
            logic.mount()
            await expectLogic(logic).toMatchValues({ aiDiagnosticsEnabled: expected })
        })
    })

    describe('setAiDiagnosticsEnabled', () => {
        it('sets loading state and dispatches updateCurrentTeam', async () => {
            logic = supportSettingsLogic()
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.setAiDiagnosticsEnabled(true)
            })
                .toDispatchActions(['setAiDiagnosticsLoading', 'updateCurrentTeam'])
                .toMatchValues({ aiDiagnosticsLoading: true })
        })

        it('clears loading state on updateCurrentTeamSuccess', async () => {
            logic = supportSettingsLogic()
            logic.mount()

            logic.actions.setAiDiagnosticsLoading(true)
            expect(logic.values.aiDiagnosticsLoading).toBe(true)

            logic.actions.updateCurrentTeamSuccess({} as TeamType)
            expect(logic.values.aiDiagnosticsLoading).toBe(false)
        })

        it('clears loading state on updateCurrentTeamFailure', async () => {
            logic = supportSettingsLogic()
            logic.mount()

            logic.actions.setAiDiagnosticsLoading(true)
            expect(logic.values.aiDiagnosticsLoading).toBe(true)

            logic.actions.updateCurrentTeamFailure('update failed')
            expect(logic.values.aiDiagnosticsLoading).toBe(false)
        })
    })

    describe('widget draft preservation on save', () => {
        it('clears the saved draft but keeps unsaved sibling drafts', async () => {
            logic = supportSettingsLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.setGreetingInputValue('new greeting')
            logic.actions.setPlaceholderTextValue('unsaved placeholder')

            // A save persists the greeting; the server echoes it back on success.
            logic.actions.updateCurrentTeamSuccess({
                conversations_settings: { widget_greeting_text: 'new greeting' },
            } as unknown as TeamType)

            expect(logic.values.greetingInputValue).toBeNull()
            expect(logic.values.placeholderTextValue).toBe('unsaved placeholder')
        })

        it('clears a bot field draft that was blanked to remove the override', async () => {
            logic = supportSettingsLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            // Clearing the input yields an empty-string draft; the save persists it as null.
            logic.actions.setSlackBotDisplayNameValue('')

            logic.actions.updateCurrentTeamSuccess({
                conversations_settings: { slack_bot_display_name: null },
            } as unknown as TeamType)

            expect(logic.values.slackBotDisplayNameValue).toBeNull()
        })

        it('keeps a whitespace-only emoji edit when an unrelated field saves', async () => {
            initKeaTests(true, {
                conversations_settings: { slack_ticket_emoji: '🎫' },
            } as unknown as TeamType)
            logic = supportSettingsLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            // The emoji saver sends the raw value, so a spaced draft is not yet persisted.
            logic.actions.setSlackTicketEmojiValue(' 🎫 ')

            // An unrelated save echoes the still-stored emoji back.
            logic.actions.updateCurrentTeamSuccess({
                conversations_settings: { slack_ticket_emoji: '🎫' },
            } as unknown as TeamType)

            expect(logic.values.slackTicketEmojiValue).toBe(' 🎫 ')
        })
    })

    describe('teamsChannelPairs selector', () => {
        it('reads the teams_channels list when present', async () => {
            initKeaTests(true, {
                conversations_settings: {
                    teams_channels: [
                        { team_id: 't1', team_name: 'Team 1', channel_id: 'ch-1', channel_name: 'Ch 1' },
                        { team_id: 't2', team_name: 'Team 2', channel_id: 'ch-2', channel_name: 'Ch 2' },
                    ],
                },
            } as unknown as TeamType)
            logic = supportSettingsLogic()
            logic.mount()
            await expectLogic(logic).toMatchValues({
                teamsChannelPairs: [
                    { team_id: 't1', team_name: 'Team 1', channel_id: 'ch-1', channel_name: 'Ch 1' },
                    { team_id: 't2', team_name: 'Team 2', channel_id: 'ch-2', channel_name: 'Ch 2' },
                ],
            })
        })

        it('falls back to legacy scalar fields when teams_channels is absent', async () => {
            initKeaTests(true, {
                conversations_settings: {
                    teams_team_id: 'legacy-team',
                    teams_team_name: 'Legacy Team',
                    teams_channel_id: 'legacy-ch',
                    teams_channel_name: 'Legacy Channel',
                },
            } as unknown as TeamType)
            logic = supportSettingsLogic()
            logic.mount()
            await expectLogic(logic).toMatchValues({
                teamsChannelPairs: [
                    {
                        team_id: 'legacy-team',
                        team_name: 'Legacy Team',
                        channel_id: 'legacy-ch',
                        channel_name: 'Legacy Channel',
                    },
                ],
            })
        })

        it('returns an empty list when nothing is configured', async () => {
            initKeaTests(true, { conversations_settings: { teams_enabled: true } } as unknown as TeamType)
            logic = supportSettingsLogic()
            logic.mount()
            await expectLogic(logic).toMatchValues({ teamsChannelPairs: [] })
        })
    })

    describe('teams channel pair actions', () => {
        it('addTeamsChannelPair posts an add action and refreshes the team', async () => {
            logic = supportSettingsLogic()
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.addTeamsChannelPair('t1', 'ch-1')
            })
                .toDispatchActions(['addTeamsChannelPair', 'loadCurrentTeam', 'installTeamsApp'])
                .toMatchValues({ teamsChannelPairLoading: null })
        })

        it('removeTeamsChannelPair posts a remove action and refreshes the team', async () => {
            logic = supportSettingsLogic()
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.removeTeamsChannelPair('ch-1')
            })
                .toDispatchActions(['removeTeamsChannelPair', 'loadCurrentTeam', 'setTeamsChannelPairLoading'])
                .toMatchValues({ teamsChannelPairLoading: null })
        })

        it('allows adding a second channel in the same group', async () => {
            const existingChannels = [
                { team_id: 't1', team_name: 'Team 1', channel_id: 'ch-1', channel_name: 'Channel 1' },
            ]
            const updatedChannels = [
                ...existingChannels,
                { team_id: 't1', team_name: 'Team 1', channel_id: 'ch-2', channel_name: 'Channel 2' },
            ]

            useMocks({
                get: {
                    '/api/conversations/v1/email/status': { configs: [] },
                    '/api/projects/:team_id/conversations/ai_reply_playbook/': PLAYBOOK_GET,
                },
                post: {
                    '/api/environments/:team_id/': async ({ request }) => [200, await request.json()],
                    '/api/conversations/v1/teams/select-channel': { ok: true, teams_channels: updatedChannels },
                    '/api/conversations/v1/teams/install': { ok: true, status: 'installed' },
                    '/api/conversations/v1/teams/channels': { channels: [] },
                },
            })

            initKeaTests(true, {
                conversations_settings: {
                    teams_enabled: true,
                    teams_channels: existingChannels,
                },
            } as unknown as TeamType)

            logic = supportSettingsLogic()
            logic.mount()

            await expectLogic(logic).toMatchValues({
                teamsChannelPairs: existingChannels,
            })

            // Verify the add action dispatches correctly
            await expectLogic(logic, () => {
                logic.actions.addTeamsChannelPair('t1', 'ch-2')
            }).toDispatchActions(['addTeamsChannelPair', 'loadCurrentTeam'])

            // Simulate the team reload completing with both channels
            teamLogic.actions.loadCurrentTeamSuccess({
                conversations_settings: { teams_enabled: true, teams_channels: updatedChannels },
            } as unknown as TeamType)

            expect(logic.values.teamsChannelPairs).toEqual(updatedChannels)
        })
    })

    describe('support playbook', () => {
        it('loads the inherited playbook on mount', async () => {
            logic = supportSettingsLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.playbook).toEqual(PLAYBOOK_GET)
            expect(logic.values.playbookDraft).toBe('')
            expect(logic.values.aiReplyCustomized).toBe(false)
        })

        it('loads a custom addendum into the draft without the default playbook', async () => {
            useMocks({
                get: {
                    '/api/conversations/v1/email/status': { configs: [] },
                    '/api/projects/:team_id/conversations/ai_reply_playbook/': {
                        ...PLAYBOOK_GET,
                        custom_instructions: 'Always greet first.',
                        is_customized: true,
                    },
                },
            })
            logic = supportSettingsLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.playbookDraft).toBe('Always greet first.')
            expect(logic.values.aiReplyCustomized).toBe(true)
            expect(logic.values.playbookDirty).toBe(false)
        })

        it('saves custom instructions and ignores a second submit while in flight', async () => {
            logic = supportSettingsLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            logic.actions.setPlaybookDraft('Always greet first.')

            await expectLogic(logic, () => {
                logic.actions.savePlaybook()
            })
                .toDispatchActions(['setPlaybookSaving', 'updateCurrentTeam'])
                .toMatchValues({ playbookSaving: true })

            await expectLogic(logic, () => {
                logic.actions.savePlaybook()
            }).toNotHaveDispatchedActions(['updateCurrentTeam'])
        })

        it('resets by PATCHing null custom instructions', async () => {
            initKeaTests(true, {
                conversations_settings: { ai_reply_custom_instructions: 'Always greet first.' },
            } as unknown as TeamType)
            logic = supportSettingsLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.resetPlaybook()
            }).toDispatchActions(['setPlaybookSaving', 'updateCurrentTeam'])
        })

        it('clears the saving guard and reloads once its own request finishes', async () => {
            useMocks({
                get: {
                    '/api/conversations/v1/email/status': { configs: [] },
                    '/api/projects/:team_id/conversations/ai_reply_playbook/': PLAYBOOK_GET,
                },
                patch: {
                    '/api/environments/:team_id/': async ({ request }) => [200, await request.json()],
                },
            })
            logic = supportSettingsLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            logic.actions.setPlaybookDraft('Always greet first.')

            await expectLogic(logic, () => {
                logic.actions.savePlaybook()
            }).toDispatchActions(['setPlaybookSaving', 'updateCurrentTeam', 'loadPlaybook'])
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.playbookSaving).toBe(false)
        })

        it('keeps the draft when the save fails, even once an unrelated save lands', async () => {
            useMocks({
                get: {
                    '/api/conversations/v1/email/status': { configs: [] },
                    '/api/projects/:team_id/conversations/ai_reply_playbook/': PLAYBOOK_GET,
                },
                patch: {
                    '/api/environments/:team_id/': () => [400, { detail: 'Nope' }],
                },
            })
            logic = supportSettingsLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            logic.actions.setPlaybookDraft('Always greet first.')

            await expectLogic(logic, () => {
                logic.actions.savePlaybook()
            }).toDispatchActions(['updateCurrentTeamFailure'])
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.updateCurrentTeamSuccess({} as TeamType, { conversations_enabled: true })
            }).toNotHaveDispatchedActions(['loadPlaybook'])

            expect(logic.values.playbookSaving).toBe(false)
            expect(logic.values.playbookDraft).toBe('Always greet first.')
        })

        it('leaves a playbook save in flight when an unrelated team update settles', async () => {
            logic = supportSettingsLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            logic.actions.setPlaybookDraft('Always greet first.')

            logic.actions.savePlaybook()
            expect(logic.values.playbookSaving).toBe(true)

            logic.actions.updateCurrentTeamSuccess({} as TeamType)
            logic.actions.updateCurrentTeamFailure('unrelated failure')
            expect(logic.values.playbookSaving).toBe(true)

            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.playbookSaving).toBe(false)
        })
    })

    describe('AI context account properties', () => {
        it('saves selected ids and ignores a second submit while in flight', async () => {
            let resolveTeamPatch: () => void = () => {}
            const releaseTeamPatch = new Promise<void>((resolve) => {
                resolveTeamPatch = resolve
            })
            useMocks({
                get: {
                    '/api/conversations/v1/email/status': { configs: [] },
                    '/api/projects/:team_id/conversations/ai_reply_playbook/': PLAYBOOK_GET,
                    '/api/projects/:team_id/conversations/ai_context_account_properties/': [
                        { id: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee', name: 'Plan' },
                    ],
                },
                patch: {
                    '/api/environments/:team_id/': async ({ request }) => {
                        const body = await request.json()
                        await releaseTeamPatch
                        return [200, body]
                    },
                },
            })
            initKeaTests(true, {
                ...MOCK_DEFAULT_TEAM,
                conversations_settings: { ai_context_account_property_ids: [] },
            } as unknown as TeamType)
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.CUSTOMER_ANALYTICS]: true })
            logic = supportSettingsLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.accountPropertyOptions).toEqual([
                { id: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee', name: 'Plan' },
            ])

            await expectLogic(logic, () => {
                logic.actions.setAiContextAccountPropertyIds(['aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'])
            })
                .toDispatchActions(['setAiContextAccountPropertiesSaving', 'updateCurrentTeam'])
                .toMatchValues({ aiContextAccountPropertiesSaving: true })

            // The first PATCH is still open, so the second submit must hit the in-flight guard.
            await expectLogic(logic, () => {
                logic.actions.setAiContextAccountPropertyIds(['aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'])
            }).toNotHaveDispatchedActions(['updateCurrentTeam'])

            resolveTeamPatch()
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.aiContextAccountPropertiesSaving).toBe(false)
        })

        it('ignores a late response from the team the user switched away from', async () => {
            const TEAM_A_OPTIONS = [{ id: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee', name: 'Team A plan' }]
            const TEAM_B_OPTIONS = [{ id: 'bbbbbbbb-cccc-dddd-eeee-ffffffffffff', name: 'Team B plan' }]
            let releaseTeamA: () => void = () => {}
            const teamAInFlight = new Promise<void>((resolve) => {
                releaseTeamA = resolve
            })
            useMocks({
                get: {
                    '/api/conversations/v1/email/status': { configs: [] },
                    '/api/projects/:team_id/conversations/ai_reply_playbook/': PLAYBOOK_GET,
                    '/api/projects/:team_id/conversations/ai_context_account_properties/': async ({ params }) => {
                        if (String(params.team_id) === String(MOCK_DEFAULT_TEAM.id)) {
                            await teamAInFlight
                            return [200, TEAM_A_OPTIONS]
                        }
                        return [200, TEAM_B_OPTIONS]
                    },
                },
            })
            initKeaTests(true, {
                ...MOCK_DEFAULT_TEAM,
                conversations_settings: { ai_context_account_property_ids: [] },
            } as unknown as TeamType)
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.CUSTOMER_ANALYTICS]: true })
            logic = supportSettingsLogic()
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadAccountPropertyOptions'])

            // Team A's request is still open, so switching teams must start a second load.
            await expectLogic(logic, () => {
                teamLogic.actions.loadCurrentTeamSuccess({
                    ...MOCK_DEFAULT_TEAM,
                    id: MOCK_DEFAULT_TEAM.id + 1,
                    conversations_settings: { ai_context_account_property_ids: [] },
                } as unknown as TeamType)
            }).toDispatchActions([
                'resetAccountPropertyOptions',
                'loadAccountPropertyOptions',
                'loadAccountPropertyOptionsSuccess',
            ])
            expect(logic.values.accountPropertyOptions).toEqual(TEAM_B_OPTIONS)

            releaseTeamA()
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.accountPropertyOptions).toEqual(TEAM_B_OPTIONS)
        })

        it('loads the options when Customer analytics resolves after mount', async () => {
            const OPTIONS = [{ id: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee', name: 'Plan' }]
            useMocks({
                get: {
                    '/api/conversations/v1/email/status': { configs: [] },
                    '/api/projects/:team_id/conversations/ai_reply_playbook/': PLAYBOOK_GET,
                    '/api/projects/:team_id/conversations/ai_context_account_properties/': OPTIONS,
                },
            })
            initKeaTests(true, {
                ...MOCK_DEFAULT_TEAM,
                conversations_settings: { ai_context_account_property_ids: [] },
            } as unknown as TeamType)
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.CUSTOMER_ANALYTICS]: false })
            logic = supportSettingsLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners().toNotHaveDispatchedActions(['loadAccountPropertyOptions'])
            expect(logic.values.accountPropertyOptions).toEqual([])

            // posthog-js can resolve the flag after the scene is already on screen.
            await expectLogic(logic, () => {
                featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.CUSTOMER_ANALYTICS]: true })
            }).toDispatchActions(['loadAccountPropertyOptions', 'loadAccountPropertyOptionsSuccess'])
            expect(logic.values.accountPropertyOptions).toEqual(OPTIONS)
        })
    })
})

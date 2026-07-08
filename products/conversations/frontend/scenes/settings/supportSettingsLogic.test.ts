import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { teamLogic } from '~/scenes/teamLogic'
import { initKeaTests } from '~/test/init'
import { TeamType } from '~/types'

import { supportSettingsLogic } from './supportSettingsLogic'

describe('supportSettingsLogic', () => {
    let logic: ReturnType<typeof supportSettingsLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                'api/conversations/v1/email/status': { configs: [] },
            },
            post: {
                'api/environments/:team_id/': async ({ request }) => [200, await request.json()],
                'api/conversations/v1/teams/select-channel': { ok: true, teams_channels: [] },
                'api/conversations/v1/teams/install': { ok: true, status: 'installed' },
                'api/conversations/v1/teams/channels': { channels: [] },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
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
                    'api/conversations/v1/email/status': { configs: [] },
                },
                post: {
                    'api/environments/:team_id/': async ({ request }) => [200, await request.json()],
                    'api/conversations/v1/teams/select-channel': { ok: true, teams_channels: updatedChannels },
                    'api/conversations/v1/teams/install': { ok: true, status: 'installed' },
                    'api/conversations/v1/teams/channels': { channels: [] },
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
})

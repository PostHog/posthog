import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { aiConsentLogic } from 'scenes/settings/organization/aiConsentLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { TOOL_DEFINITIONS, ToolDefinition } from './max-constants'
import { STATIC_TOOLS, maxGlobalLogic } from './maxGlobalLogic'
import { SIDE_PANEL_PANEL_ID, maxLogic } from './maxLogic'
import { MOCK_CONVERSATION, MOCK_CONVERSATION_ID, maxMocks } from './testUtils'

describe('maxGlobalLogic tool definitions', () => {
    it('all tool descriptions start with their name when provided', () => {
        const definitionsToCheck = (
            STATIC_TOOLS as (Pick<ToolDefinition, 'name' | 'description'> & {
                subtools?: Record<string, ToolDefinition>
            })[]
        ).concat(Object.values(TOOL_DEFINITIONS))
        for (const tool of definitionsToCheck) {
            if (tool.subtools) {
                for (const subtool of Object.values(tool.subtools)) {
                    if (subtool.description) {
                        expect(subtool.description.startsWith(subtool.name)).toBe(true)
                    }
                }
            } else if (tool.description) {
                expect(tool.description.startsWith(tool.name)).toBe(true)
            }
        }
    })
})

describe('maxGlobalLogic', () => {
    let logic: ReturnType<typeof maxGlobalLogic.build>

    beforeEach(() => {
        useMocks(maxMocks)
        initKeaTests()
        logic = maxGlobalLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    // Opening a conversation in the side panel must surface it in the side panel chat without
    // replacing the main content. The side panel floats over whatever scene you're on; the rendered
    // scene is chosen by the route, so the page (insight, survey, …) must stay put.
    describe('openSidePanelMax', () => {
        it.each(['/insights/abc123', '/surveys/xyz789'])(
            'opens the conversation in the side panel without replacing the main content on %s',
            async (page) => {
                useMocks({ get: { '/api/environments/:team_id/conversations/:id': MOCK_CONVERSATION } })
                router.actions.push(page)

                await expectLogic(logic, () => {
                    logic.actions.openSidePanelMax(MOCK_CONVERSATION_ID)
                }).toFinishAllListeners()

                const sidePanelMax = maxLogic.findMounted({ panelId: SIDE_PANEL_PANEL_ID })
                expect(sidePanelMax?.values.conversationId).toBe(MOCK_CONVERSATION_ID)
                expect(router.values.location.pathname.endsWith(page)).toBe(true)

                sidePanelMax?.unmount()
            }
        )
    })

    // The conversation detail endpoint can return an empty body; letting that null into
    // conversationHistory crashes every consumer that dereferences entries (e.g. the AI chat nav tab).
    describe('loadConversation', () => {
        it.each([
            { case: 'a conversation already in history', conversationId: MOCK_CONVERSATION_ID },
            { case: 'a conversation not in history', conversationId: 'unknown-conversation-id' },
        ])('keeps history intact when the API returns a null body for $case', async ({ conversationId }) => {
            // Let the mount-time loadConversationHistory settle so it can't overwrite the seeded history
            await expectLogic(logic).toDispatchActions(['loadConversationHistorySuccess'])
            logic.actions.prependOrReplaceConversation(MOCK_CONVERSATION)
            jest.spyOn(api.conversations, 'get').mockResolvedValue(null as any)

            await expectLogic(logic, () => {
                logic.actions.loadConversation(conversationId)
            }).toFinishAllListeners()

            expect(logic.values.conversationHistory).toHaveLength(1)
            expect(logic.values.conversationHistory[0]?.id).toBe(MOCK_CONVERSATION_ID)
        })
    })

    describe('isMaxAvailable selector', () => {
        it.each([
            { realm: 'a not-yet-loaded preflight', preflight: null, expected: true },
            { realm: 'PostHog Cloud', preflight: { cloud: true }, expected: true },
            {
                realm: 'self-hosted with an Anthropic key',
                preflight: { cloud: false, is_debug: false, anthropic_available: true },
                expected: true,
            },
            {
                realm: 'self-hosted without a key',
                preflight: { cloud: false, is_debug: false, anthropic_available: false },
                expected: false,
            },
        ])('is $expected on $realm', async ({ preflight, expected }) => {
            preflightLogic.actions.loadPreflightSuccess(preflight as any)

            await expectLogic(logic).toMatchValues({ isMaxAvailable: expected })
        })
    })

    // Consent state (accept/dismiss/request-access) now lives in aiConsentLogic (see aiConsentLogic.test.ts)
    // and is only forwarded here via `connect` so the ~15 existing consumers keep reading it off
    // maxGlobalLogic unchanged. This guards the forwarding wiring itself — a mistake here (e.g. connecting
    // to the wrong source, or a stale value) wouldn't be caught by typechecking, since the shape stays the
    // same either way.
    describe('consent forwarding from aiConsentLogic', () => {
        it('dismissing via maxGlobalLogic updates aiConsentLogic and is reflected back', () => {
            const consent = aiConsentLogic()
            consent.mount()

            // Same underlying state, not two independent copies.
            expect(logic.values.dataProcessingAccepted).toBe(consent.values.dataProcessingAccepted)
            expect(logic.values.dataProcessingDismissed).toBe(false)

            logic.actions.dismissDataProcessing()

            expect(consent.values.dataProcessingDismissed).toBe(true)
            expect(logic.values.dataProcessingDismissed).toBe(true)

            consent.unmount()
        })
    })

    describe('editInsightToolRegistered selector', () => {
        it('returns true when contextual create_insight tool is registered', async () => {
            // Initially should be false (only static tool available)
            await expectLogic(logic).toMatchValues({
                editInsightToolRegistered: false,
            })

            logic.actions.registerTool({
                ...TOOL_DEFINITIONS.create_insight,
                identifier: 'create_insight',
            })

            // Now should be true (contextual tool is registered)
            await expectLogic(logic).toMatchValues({
                editInsightToolRegistered: true,
            })
        })
    })

    // The flag is the only thing that may expose the new posthog_ai surface — without the gate a stored
    // preference (or a missing default) would leak it to every user. Lock in: flag off collapses to legacy
    // regardless of the stored mode; flag on passes the stored mode through.
    describe('effectivePhaiView selector', () => {
        it.each([
            { flagOn: false, mode: 'new', expected: 'legacy' },
            { flagOn: false, mode: 'legacy', expected: 'legacy' },
            { flagOn: true, mode: 'new', expected: 'new' },
            { flagOn: true, mode: 'legacy', expected: 'legacy' },
        ] as const)(
            'is $expected when sandbox flag is $flagOn and stored mode is $mode',
            async ({ flagOn, mode, expected }) => {
                featureFlagLogic.actions.setFeatureFlags(
                    flagOn ? [FEATURE_FLAGS.PHAI_SANDBOX_MODE] : [],
                    flagOn ? { [FEATURE_FLAGS.PHAI_SANDBOX_MODE]: true } : {}
                )
                logic.actions.setPhaiViewMode(mode)

                await expectLogic(logic).toMatchValues({ effectivePhaiView: expected })
            }
        )
    })
})

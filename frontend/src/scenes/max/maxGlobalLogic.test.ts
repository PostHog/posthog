import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

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

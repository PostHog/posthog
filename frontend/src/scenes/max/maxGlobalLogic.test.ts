import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { ApiError } from 'lib/api-error'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AppContext } from '~/types'

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
})

describe('maxGlobalLogic conversation history loading', () => {
    let logic: ReturnType<typeof maxGlobalLogic.build>
    let listSpy: jest.SpyInstance

    afterEach(() => {
        logic?.unmount()
        listSpy?.mockRestore()
        jest.restoreAllMocks()
        // Tests here set `current_user: null`; clear so the next test gets a fresh `initKeaTests` bootstrap.
        delete window.POSTHOG_APP_CONTEXT
    })

    function mountUnauthenticated(): void {
        window.POSTHOG_APP_CONTEXT = { current_user: null } as unknown as AppContext
        initKeaTests()
        listSpy = jest.spyOn(api.conversations, 'list')
        logic = maxGlobalLogic()
        logic.mount()
    }

    it('does not fetch conversation history when the user is unauthenticated', async () => {
        useMocks(maxMocks)
        mountUnauthenticated()

        await expectLogic(logic).delay(0)

        expect(userLogic.values.user).toBeNull()
        expect(listSpy).not.toHaveBeenCalled()
        expect(logic.values.conversationHistory).toEqual([])
    })

    it('fetches conversation history once the user becomes authenticated', async () => {
        useMocks(maxMocks)
        mountUnauthenticated()
        await expectLogic(logic).delay(0)
        expect(listSpy).not.toHaveBeenCalled()

        await expectLogic(logic, () => {
            userLogic.actions.loadUserSuccess(MOCK_DEFAULT_USER)
        }).toDispatchActions(['loadConversationHistory', 'loadConversationHistorySuccess'])

        expect(listSpy).toHaveBeenCalledTimes(1)
    })

    it.each([401, 403])('stays silent when conversation history fails with %s', async (status) => {
        useMocks(maxMocks)
        initKeaTests()
        const toastSpy = jest.spyOn(lemonToast, 'error')
        listSpy = jest.spyOn(api.conversations, 'list').mockRejectedValue(new ApiError('Nope', status))
        logic = maxGlobalLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadConversationHistory', 'loadConversationHistoryFailure'])

        expect(toastSpy).not.toHaveBeenCalled()
    })

    it('shows a toast when conversation history fails with a non-auth error', async () => {
        useMocks(maxMocks)
        initKeaTests()
        const toastSpy = jest.spyOn(lemonToast, 'error')
        listSpy = jest.spyOn(api.conversations, 'list').mockRejectedValue(new ApiError('Boom', 500))
        logic = maxGlobalLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadConversationHistory', 'loadConversationHistoryFailure'])

        expect(toastSpy).toHaveBeenCalled()
    })
})

import { router } from 'kea-router'
import { expectLogic, partial } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { useMocks } from '~/mocks/jest'
import { AgentMode } from '~/queries/schema/schema-assistant-messages'
import { initKeaTests } from '~/test/init'
import { SidePanelTab } from '~/types'

import { QUESTION_SUGGESTIONS_DATA, maxLogic } from './maxLogic'
import { maxThreadLogic } from './maxThreadLogic'
import { maxMocks } from './testUtils'

describe('maxLogic', () => {
    let logic: ReturnType<typeof maxLogic.build>
    let threadLogic: ReturnType<typeof maxThreadLogic.build> | null = null

    beforeEach(() => {
        localStorage.clear()
        useMocks(maxMocks)
        initKeaTests()
    })

    afterEach(() => {
        threadLogic?.unmount()
        threadLogic = null
        sidePanelStateLogic.unmount()
        // Reset maxLogic state before unmounting to prevent state leaking to next test
        if (logic?.isMounted()) {
            logic.actions.startNewConversation()
        }
        logic?.unmount()
    })

    it('sets the question when URL has hash param #panel=max:Foo', async () => {
        // Set up sidePanelStateLogic with the options before mounting maxLogic
        sidePanelStateLogic.mount()
        await expectLogic(sidePanelStateLogic, () => {
            sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Max, 'Foo')
        }).toDispatchActions(['openSidePanel'])

        // Mount maxLogic after setting up the sidePanelStateLogic state
        logic = maxLogic({ tabId: 'sidepanel' })
        logic.mount()

        // Check that the question has been set to "Foo"
        await expectLogic(logic).toMatchValues({
            question: 'Foo',
        })
    })

    it('sets autoRun and question when URL has hash param #panel=max:!Foo', async () => {
        // Set up sidePanelStateLogic with the options before mounting maxLogic
        sidePanelStateLogic.mount()
        await expectLogic(sidePanelStateLogic, () => {
            sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Max, '!Foo')
        }).toDispatchActions(['openSidePanel'])

        // Must create the logic first to spy on its actions
        logic = maxLogic({ tabId: 'sidepanel' })
        logic.mount()

        // Only mount maxLogic after setting up the router and sidePanelStateLogic
        await expectLogic(logic).toMatchValues({
            autoRun: true,
            question: 'Foo',
        })
    })

    it('does not reset conversation when 404 occurs during active message generation', async () => {
        router.actions.push('', {}, { panel: 'max' })
        sidePanelStateLogic.mount()

        const mockConversationId = 'new-conversation-id'

        useMocks({
            ...maxMocks,
            get: {
                ...maxMocks.get,
                '/api/environments/:team_id/conversations/': { results: [] },
                [`/api/environments/:team_id/conversations/${mockConversationId}`]: () => [
                    404,
                    { detail: 'Not found' },
                ],
            },
        })

        logic = maxLogic({ tabId: 'test' })
        logic.mount()

        // Wait for initial conversationHistory load to complete
        await expectLogic(logic).toDispatchActions(['loadConversationHistorySuccess'])

        // Simulate asking Max a question (which starts a new conversation)
        await expectLogic(logic, () => {
            logic.actions.setQuestion('Test question')
            logic.actions.setConversationId(mockConversationId)
        }).toDispatchActions(['setQuestion', 'setConversationId'])

        // Now simulate the race condition: when pollConversation is called from loadConversationHistorySuccess,
        // it will get a 404 for the conversation that doesn't exist yet on the backend
        // but is being generated on the frontend
        await expectLogic(logic, () => {
            logic.actions.pollConversation(mockConversationId, 0, 0)
        }).toFinishAllListeners()

        // Wait a bit for any async operations
        await expectLogic(logic).delay(50)

        // The conversation should NOT be reset - conversationId should still be set
        await expectLogic(logic).toMatchValues({
            conversationId: mockConversationId,
        })

        // Verify no error toast was shown and no reset occurred
        expect(Array.isArray(logic.values.conversationHistory)).toBe(true)
    })

    it('manages suggestion group selection correctly', async () => {
        logic = maxLogic({ tabId: 'test' })
        logic.mount()

        await expectLogic(logic).toMatchValues({
            activeSuggestionGroup: null,
        })

        await expectLogic(logic, () => {
            logic.actions.setActiveGroup(QUESTION_SUGGESTIONS_DATA[1])
        })
            .toDispatchActions(['setActiveGroup'])
            .toMatchValues({
                activeSuggestionGroup: partial({
                    label: 'SQL',
                }),
            })

        // Test setting to null clears the selection
        logic.actions.setActiveGroup(null)

        await expectLogic(logic).toMatchValues({
            activeSuggestionGroup: null,
        })

        // Test setting to a different index
        logic.actions.setActiveGroup(QUESTION_SUGGESTIONS_DATA[0])

        await expectLogic(logic).toMatchValues({
            activeSuggestionGroup: partial({
                label: 'Product analytics',
            }),
        })
    })

    it('generates and uses frontendConversationId correctly', async () => {
        logic = maxLogic({ tabId: 'test' })
        logic.mount()

        const initialFrontendId = logic.values.frontendConversationId
        expect(initialFrontendId).toBeTruthy()
        expect(typeof initialFrontendId).toBe('string')

        // Test that the ID is a valid UUID
        const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
        expect(initialFrontendId).toMatch(uuidRegex)

        // Test that starting a new conversation generates a new frontend ID
        await expectLogic(logic, () => {
            logic.actions.startNewConversation()
        }).toMatchValues({
            frontendConversationId: expect.not.stringMatching(initialFrontendId),
        })

        expect(logic.values.frontendConversationId).toBeTruthy()
        expect(logic.values.frontendConversationId).not.toBe(initialFrontendId)

        // Test that the new ID is also a valid UUID
        expect(logic.values.frontendConversationId).toMatch(uuidRegex)
    })

    it('uses threadLogicKey correctly with frontendConversationId', async () => {
        logic = maxLogic({ tabId: 'test' })
        logic.mount()

        // When no conversation ID is set, should use frontendConversationId
        await expectLogic(logic).toMatchValues({
            threadLogicKey: logic.values.frontendConversationId,
        })

        // When conversation ID is set, should use it
        await expectLogic(logic, () => {
            logic.actions.setConversationId('test-conversation-id')
        }).toMatchValues({
            threadLogicKey: 'test-conversation-id',
        })
    })

    describe('mode URL parameter', () => {
        beforeEach(() => {
            // Enable feature flags for gated modes
            featureFlagLogic.mount()
            featureFlagLogic.actions.setFeatureFlags([], {
                [FEATURE_FLAGS.MAX_DEEP_RESEARCH]: true,
                [FEATURE_FLAGS.PHAI_PLAN_MODE]: true,
            })
        })

        afterEach(() => {
            featureFlagLogic.unmount()
        })

        it('parses mode=research:!Question correctly', async () => {
            sidePanelStateLogic.mount()
            await expectLogic(sidePanelStateLogic, () => {
                sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Max, 'mode=research:!Question')
            }).toDispatchActions(['openSidePanel'])

            logic = maxLogic({ tabId: 'sidepanel' })
            logic.mount()

            await expectLogic(logic).toMatchValues({
                autoRun: true,
                question: 'Question',
            })

            threadLogic = maxThreadLogic({
                tabId: 'sidepanel',
                conversationId: logic.values.frontendConversationId,
                conversation: null,
            })
            threadLogic.mount()

            await expectLogic(threadLogic).toMatchValues({
                agentMode: AgentMode.Research,
            })
        })

        it('parses mode=product_analytics:Question correctly', async () => {
            sidePanelStateLogic.mount()
            await expectLogic(sidePanelStateLogic, () => {
                sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Max, 'mode=product_analytics:Question')
            }).toDispatchActions(['openSidePanel'])

            logic = maxLogic({ tabId: 'sidepanel' })
            logic.mount()

            await expectLogic(logic).toMatchValues({
                autoRun: false,
                question: 'Question',
            })

            threadLogic = maxThreadLogic({
                tabId: 'sidepanel',
                conversationId: logic.values.frontendConversationId,
                conversation: null,
            })
            threadLogic.mount()

            await expectLogic(threadLogic).toMatchValues({
                agentMode: AgentMode.ProductAnalytics,
            })
        })

        it('parses mode=sql:!Write a query correctly', async () => {
            sidePanelStateLogic.mount()
            await expectLogic(sidePanelStateLogic, () => {
                sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Max, 'mode=sql:!Write a query')
            }).toDispatchActions(['openSidePanel'])

            logic = maxLogic({ tabId: 'sidepanel' })
            logic.mount()

            await expectLogic(logic).toMatchValues({
                autoRun: true,
                question: 'Write a query',
            })

            threadLogic = maxThreadLogic({
                tabId: 'sidepanel',
                conversationId: logic.values.frontendConversationId,
                conversation: null,
            })
            threadLogic.mount()

            await expectLogic(threadLogic).toMatchValues({
                agentMode: AgentMode.SQL,
            })
        })

        it('parses mode=auto:!Question correctly (null mode)', async () => {
            // Mount maxLogic first and reset state to ensure clean slate
            logic = maxLogic({ tabId: 'sidepanel' })
            logic.mount()
            logic.actions.startNewConversation()

            // Now set up sidePanelStateLogic with the options
            sidePanelStateLogic.mount()

            // Dispatch openSidePanel - the listener in maxLogic will process this
            await expectLogic(logic, () => {
                sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Max, 'mode=auto:!Question')
            }).toMatchValues({
                autoRun: true,
                question: 'Question',
            })

            threadLogic = maxThreadLogic({
                tabId: 'sidepanel',
                conversationId: logic.values.frontendConversationId,
                conversation: null,
            })
            threadLogic.mount()

            await expectLogic(threadLogic).toMatchValues({
                agentMode: null,
            })
        })

        it('parses mode=research correctly (mode only, no question)', async () => {
            // Mount maxLogic first and reset state to ensure clean slate
            logic = maxLogic({ tabId: 'sidepanel' })
            logic.mount()
            logic.actions.startNewConversation()

            // Now set up sidePanelStateLogic with the options
            sidePanelStateLogic.mount()

            // Dispatch openSidePanel - the listener in maxLogic will process this
            await expectLogic(logic, () => {
                sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Max, 'mode=research')
            }).toMatchValues({
                autoRun: false,
                question: '',
            })

            threadLogic = maxThreadLogic({
                tabId: 'sidepanel',
                conversationId: logic.values.frontendConversationId,
                conversation: null,
            })
            threadLogic.mount()

            await expectLogic(threadLogic).toMatchValues({
                agentMode: AgentMode.Research,
            })
        })

        it('parses mode=invalid_mode:!Question correctly (ignores invalid mode)', async () => {
            sidePanelStateLogic.mount()
            await expectLogic(sidePanelStateLogic, () => {
                sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Max, 'mode=invalid_mode:!Question')
            }).toDispatchActions(['openSidePanel'])

            logic = maxLogic({ tabId: 'sidepanel' })
            logic.mount()

            await expectLogic(logic).toMatchValues({
                autoRun: true,
                question: 'Question',
            })

            threadLogic = maxThreadLogic({
                tabId: 'sidepanel',
                conversationId: logic.values.frontendConversationId,
                conversation: null,
            })
            threadLogic.mount()

            await expectLogic(threadLogic).toMatchValues({
                agentMode: null,
            })
        })

        it('parses !My question correctly (backwards compatibility)', async () => {
            // Mount maxLogic first and reset state to ensure clean slate
            logic = maxLogic({ tabId: 'sidepanel' })
            logic.mount()
            logic.actions.startNewConversation()

            // Now set up sidePanelStateLogic with the options
            sidePanelStateLogic.mount()

            // Dispatch openSidePanel - the listener in maxLogic will process this
            await expectLogic(logic, () => {
                sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Max, '!My question')
            }).toMatchValues({
                autoRun: true,
                question: 'My question',
            })

            threadLogic = maxThreadLogic({
                tabId: 'sidepanel',
                conversationId: logic.values.frontendConversationId,
                conversation: null,
            })
            threadLogic.mount()

            await expectLogic(threadLogic).toMatchValues({
                agentMode: null,
            })
        })
    })
})

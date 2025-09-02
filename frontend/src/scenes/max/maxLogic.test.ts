import { router } from 'kea-router'
import { expectLogic, partial } from 'kea-test-utils'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { SidePanelTab } from '~/types'

import { maxLogic } from './maxLogic'
import { maxMocks, mockStream } from './testUtils'

describe('maxLogic', () => {
    let logic: ReturnType<typeof maxLogic.build>

    beforeEach(() => {
        useMocks(maxMocks)
        initKeaTests()
    })

    afterEach(() => {
        sidePanelStateLogic.unmount()
        logic?.unmount()
    })

    it('sets the question when URL has hash param #panel=max:Foo', async () => {
        // Set up router with #panel=max:Foo
        router.actions.push('', {}, { panel: 'max:Foo' })
        sidePanelStateLogic.mount()

        // Mount maxLogic after setting up the sidePanelStateLogic state
        logic = maxLogic()
        logic.mount()

        // Check that the question has been set to "Foo" (via sidePanelStateLogic automatically)
        await expectLogic(logic).toMatchValues({
            question: 'Foo',
        })
    })

    it('sets autoRun and question when URL has hash param #panel=max:!Foo', async () => {
        // Set up router with #panel=max:!Foo
        router.actions.push('', {}, { panel: 'max:!Foo' })
        sidePanelStateLogic.mount()

        // Must create the logic first to spy on its actions
        logic = maxLogic()
        logic.mount()

        // Only mount maxLogic after setting up the router and sidePanelStateLogic
        await expectLogic(logic).toMatchValues({
            autoRun: true,
            question: 'Foo',
        })
    })

    it('resets the thread when a conversation has not been found', async () => {
        router.actions.push('', { chat: 'err' }, { panel: 'max' })
        sidePanelStateLogic.mount()

        useMocks({
            ...maxMocks,
            get: {
                ...maxMocks.get,
                '/api/environments/:team_id/conversations/err': () => [404, { detail: 'Not found' }],
            },
        })

        const streamSpy = mockStream()

        // mount logic
        logic = maxLogic()
        logic.mount()

        await expectLogic(logic).delay(200)
        await expectLogic(logic).toMatchValues({
            conversationId: null,
            conversationHistory: [],
        })
        expect(streamSpy).not.toHaveBeenCalled()
    })

    it('manages suggestion group selection correctly', async () => {
        logic = maxLogic()
        logic.mount()

        await expectLogic(logic).toMatchValues({
            activeSuggestionGroup: null,
        })

        // Get allSuggestions from the logic values
        const { allSuggestions } = logic.values

        await expectLogic(logic, () => {
            logic.actions.setActiveGroup(allSuggestions[1])
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
        logic.actions.setActiveGroup(allSuggestions[0])

        await expectLogic(logic).toMatchValues({
            activeSuggestionGroup: partial({
                label: 'Product analytics',
            }),
        })
    })

    it('generates and uses frontendConversationId correctly', async () => {
        logic = maxLogic()
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
        logic = maxLogic()
        logic.mount()

        // When no conversation ID is set, should use frontendConversationId
        await expectLogic(logic).toMatchValues({
            threadLogicKey: logic.values.frontendConversationId,
        })

        // When conversation ID is set, should use conversationId when not in threadKeys
        await expectLogic(logic, () => {
            logic.actions.setConversationId('test-conversation-id')
        }).toMatchValues({
            threadLogicKey: 'test-conversation-id', // Uses conversationId when not in threadKeys
        })

        // When threadKey is set for conversation ID, should use that
        await expectLogic(logic, () => {
            logic.actions.setThreadKey('test-conversation-id', 'custom-thread-key')
        }).toMatchValues({
            threadLogicKey: 'custom-thread-key',
        })
    })

    describe('handleInitialPrompt JSON parsing', () => {
        it('handles JSON options with prompt and suggestions correctly', async () => {
            logic = maxLogic()
            logic.mount()

            const jsonOptions = JSON.stringify({
                prompt: 'Test prompt',
                suggestions: ['Create a funnel of the Pirate Metrics (AARRR)'],
            })

            // Simulate opening side panel with JSON options
            await expectLogic(logic, () => {
                sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Max, jsonOptions)
            })
                .toDispatchActions(['setQuestion', 'setActiveGroup'])
                .toMatchValues({
                    question: 'Test prompt',
                    activeSuggestionGroup: partial({
                        label: 'Product analytics',
                    }),
                })
        })

        it('handles JSON options with autoRun prompt correctly', async () => {
            logic = maxLogic()
            logic.mount()

            const jsonOptions = JSON.stringify({
                prompt: '!Auto run prompt',
                suggestions: ['Write an SQL query to…'],
            })

            await expectLogic(logic, () => {
                sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Max, jsonOptions)
            })
                .toDispatchActions(['setQuestion', 'setAutoRun', 'setActiveGroup'])
                .toMatchValues({
                    question: 'Auto run prompt',
                    autoRun: true,
                    activeSuggestionGroup: partial({
                        label: 'SQL',
                    }),
                })
        })

        it('handles JSON options without suggestions gracefully', async () => {
            logic = maxLogic()
            logic.mount()

            const jsonOptions = JSON.stringify({
                prompt: 'Just a prompt',
            })

            await expectLogic(logic, () => {
                sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Max, jsonOptions)
            })
                .toDispatchActions(['setQuestion'])
                .toMatchValues({
                    question: 'Just a prompt',
                    activeSuggestionGroup: null,
                })
        })

        it('handles JSON options with non-matching suggestions gracefully', async () => {
            logic = maxLogic()
            logic.mount()

            const jsonOptions = JSON.stringify({
                prompt: 'Test prompt',
                suggestions: ['Non-existent suggestion that matches nothing'],
            })

            await expectLogic(logic, () => {
                sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Max, jsonOptions)
            })
                .toDispatchActions(['setQuestion'])
                .toMatchValues({
                    question: 'Test prompt',
                    activeSuggestionGroup: null,
                })
        })

        it('handles JSON options with empty suggestions array gracefully', async () => {
            logic = maxLogic()
            logic.mount()

            const jsonOptions = JSON.stringify({
                prompt: 'Test prompt',
                suggestions: [],
            })

            await expectLogic(logic, () => {
                sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Max, jsonOptions)
            })
                .toDispatchActions(['setQuestion'])
                .toMatchValues({
                    question: 'Test prompt',
                    activeSuggestionGroup: null,
                })
        })

        it('falls back to legacy string handling for invalid JSON', async () => {
            logic = maxLogic()
            logic.mount()

            const invalidJsonOptions = 'Invalid JSON string'

            await expectLogic(logic, () => {
                sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Max, invalidJsonOptions)
            })
                .toDispatchActions(['setQuestion'])
                .toMatchValues({
                    question: 'Invalid JSON string',
                    activeSuggestionGroup: null,
                })
        })

        it('falls back to legacy string handling for JSON without prompt field', async () => {
            logic = maxLogic()
            logic.mount()

            const jsonWithoutPrompt = JSON.stringify({
                someOtherField: 'value',
            })

            await expectLogic(logic, () => {
                sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Max, jsonWithoutPrompt)
            })
                .toDispatchActions(['setQuestion'])
                .toMatchValues({
                    question: jsonWithoutPrompt,
                    activeSuggestionGroup: null,
                })
        })

        it('handles legacy string options with autoRun correctly', async () => {
            logic = maxLogic()
            logic.mount()

            await expectLogic(logic, () => {
                sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Max, '!Legacy autorun prompt')
            })
                .toDispatchActions(['setQuestion', 'setAutoRun'])
                .toMatchValues({
                    question: 'Legacy autorun prompt',
                    autoRun: true,
                    activeSuggestionGroup: null,
                })
        })

        it('handles multiple suggestion matches correctly (picks first match)', async () => {
            logic = maxLogic()
            logic.mount()

            // Use suggestions that could match multiple groups
            const jsonOptions = JSON.stringify({
                prompt: 'Test prompt',
                suggestions: [
                    'Create a funnel of the Pirate Metrics (AARRR)', // Product analytics
                    'Write an SQL query to…', // SQL
                ],
            })

            await expectLogic(logic, () => {
                sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Max, jsonOptions)
            })
                .toDispatchActions(['setQuestion', 'setActiveGroup'])
                .toMatchValues({
                    question: 'Test prompt',
                    // Should pick the first matching group (Product analytics)
                    activeSuggestionGroup: partial({
                        label: 'Product analytics',
                    }),
                })
        })
    })
})

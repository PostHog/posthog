import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { initKeaTests } from '~/test/init'

import { maxLogic } from './maxLogic'

describe('maxLogic', () => {
    let logic: ReturnType<typeof maxLogic.build>

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        sidePanelStateLogic.unmount()
        logic?.unmount()
    })

    it("doesn't mount sidePanelStateLogic if it's not already mounted", async () => {
        // Mount maxLogic after setting up the sidePanelStateLogic state
        logic = maxLogic()
        logic.mount()

        // Check that sidePanelStateLogic was not mounted
        expect(sidePanelStateLogic.isMounted()).toBe(false)
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

    it('calls askMax when URL has hash param #panel=max:!Foo', async () => {
        // Set up router with #panel=max:!Foo
        router.actions.push('', {}, { panel: 'max:!Foo' })
        sidePanelStateLogic.mount()

        // Spy on askMax action
        // Must create the logic first to spy on its actions
        logic = maxLogic()
        const askMaxSpy = jest.spyOn(logic.actions, 'askMax')

        // Only mount maxLogic after setting up the router and sidePanelStateLogic
        logic.mount()

        // Check that askMax has been called with "Foo" (via sidePanelStateLogic automatically)
        expect(askMaxSpy).toHaveBeenCalledWith('Foo')
    })

    it('manages suggestion group selection correctly', async () => {
        logic = maxLogic()
        logic.mount()

        await expectLogic(logic).toMatchValues({
            activeSuggestionGroupIndex: null,
            activeSuggestionGroup: undefined,
        })

        await expectLogic(logic, () => {
            logic.actions.setActiveGroup(1)
        })
            .toDispatchActions(['setActiveGroup'])
            .toMatchValues({
                activeSuggestionGroupIndex: 1,
                activeSuggestionGroup: expect.objectContaining({
                    label: 'Product Analytics',
                    suggestions: expect.arrayContaining([
                        expect.objectContaining({
                            label: 'Create a funnel of the Pirate Metrics (AARRR)',
                        }),
                    ]),
                }),
            })

        // Test setting to null clears the selection
        logic.actions.setActiveGroup(null)

        await expectLogic(logic).toMatchValues({
            activeSuggestionGroupIndex: null,
            activeSuggestionGroup: undefined,
        })

        // Test setting to a different index
        logic.actions.setActiveGroup(0)

        await expectLogic(logic).toMatchValues({
            activeSuggestionGroupIndex: 0,
            activeSuggestionGroup: expect.objectContaining({
                label: 'SQL',
                suggestions: expect.arrayContaining([
                    expect.objectContaining({
                        label: 'Generate an SQL query to',
                        content: 'Generate an SQL query to ',
                    }),
                ]),
            }),
        })
    })
})

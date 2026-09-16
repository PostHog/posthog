import { initKeaTests } from '~/test/init'

import { elementsLogic } from './elementsLogic'

describe('elementsLogic', () => {
    let logic: ReturnType<typeof elementsLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.useFakeTimers()
        // jsdom lays nothing out, and an element without a rect counts as invisible
        jest.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({
            width: 10,
            height: 10,
            top: 0,
            left: 0,
            bottom: 10,
            right: 10,
            x: 0,
            y: 0,
            toJSON: () => ({}),
        } as DOMRect)
        document.body.innerHTML = '<button id="open-menu">Menu</button>'
        logic = elementsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
        jest.useRealTimers()
        document.body.innerHTML = ''
    })

    it('adds click targets that the page reveals while the picker is on', async () => {
        logic.actions.enableInspect()
        expect(logic.values.inspectElements.map(({ element }) => element.id)).toEqual(['open-menu'])

        document.body.insertAdjacentHTML('beforeend', '<button id="inside-menu">Inside the menu</button>')
        // the observer reports mutations in a microtask, the rescan itself is debounced
        await Promise.resolve()
        jest.advanceTimersByTime(500)

        expect(logic.values.inspectElements.map(({ element }) => element.id)).toEqual(['open-menu', 'inside-menu'])
    })
})

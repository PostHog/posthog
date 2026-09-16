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
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
        jest.useRealTimers()
        document.body.innerHTML = ''
    })

    it.each([
        {
            reveal: 'the page appends it',
            html: '<button id="open-menu">Menu</button>',
            revealElement: () =>
                document.body.insertAdjacentHTML('beforeend', '<button id="inside-menu">Inside the menu</button>'),
        },
        {
            reveal: 'an ancestor attribute shows it',
            html:
                '<button id="open-menu">Menu</button>' +
                '<div id="menu" style="display: none"><button id="inside-menu">Inside the menu</button></div>',
            revealElement: () => document.getElementById('menu')?.setAttribute('style', 'display: block'),
        },
    ])('adds a click target when $reveal while the picker is on', async ({ html, revealElement }) => {
        // the page has to be in place before the picker starts, so that only the reveal mutates it
        document.body.innerHTML = html
        logic = elementsLogic()
        logic.mount()

        logic.actions.enableInspect()
        expect(logic.values.inspectElements.map(({ element }) => element.id)).toEqual(['open-menu'])

        revealElement()
        // the observer reports mutations in a microtask, the rescan itself is debounced
        await Promise.resolve()
        jest.advanceTimersByTime(500)

        expect(logic.values.inspectElements.map(({ element }) => element.id)).toEqual(['open-menu', 'inside-menu'])
    })
})

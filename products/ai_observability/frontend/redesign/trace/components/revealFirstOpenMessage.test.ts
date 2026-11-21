import { revealFirstOpenMessage } from './revealFirstOpenMessage'

const SCROLLERS = ['page', 'panel', 'inner'] as const
type Scroller = (typeof SCROLLERS)[number]

interface Layout {
    panelIsFixed: boolean
    overflowing: Scroller[]
}

function scrollableBox(name: Scroller, { overflowing }: Layout): HTMLElement {
    const box = document.createElement('div')
    box.style.overflowY = 'auto'
    Object.defineProperty(box, 'clientHeight', { value: 500 })
    Object.defineProperty(box, 'scrollHeight', { value: overflowing.includes(name) ? 2000 : 500 })
    box.scrollTo = jest.fn()
    return box
}

function mountTrace(layout: Layout): { container: HTMLElement; scrollers: Record<Scroller, HTMLElement> } {
    const page = scrollableBox('page', layout)
    const panel = scrollableBox('panel', layout)
    if (layout.panelIsFixed) {
        panel.style.position = 'fixed'
    }
    const inner = scrollableBox('inner', layout)
    const container = document.createElement('div')
    container.innerHTML = `
        <button data-attr="trace-view-message-toggle" aria-expanded="false"></button>
        <button data-attr="trace-view-message-toggle" aria-expanded="true"></button>
    `
    inner.append(container)
    panel.append(inner)
    page.append(panel)
    document.body.append(page)
    return { container, scrollers: { page, panel, inner } }
}

function scrolled(scrollers: Record<Scroller, HTMLElement>): Scroller[] {
    return SCROLLERS.filter((name) => jest.mocked(scrollers[name].scrollTo).mock.calls.length > 0)
}

describe('revealFirstOpenMessage', () => {
    afterEach(() => {
        document.body.innerHTML = ''
    })

    test.each<[string, Layout, Scroller[]]>([
        [
            'leaves the page alone when nothing in the fixed drawer overflows',
            { panelIsFixed: true, overflowing: ['page'] },
            [],
        ],
        [
            'scrolls an overflowing scroller inside the fixed drawer',
            { panelIsFixed: true, overflowing: ['page', 'inner'] },
            ['inner'],
        ],
        [
            'scrolls the fixed drawer when it overflows itself',
            { panelIsFixed: true, overflowing: ['page', 'panel'] },
            ['panel'],
        ],
        [
            'scrolls the nearest overflowing ancestor when nothing is fixed',
            { panelIsFixed: false, overflowing: ['page'] },
            ['page'],
        ],
    ])('%s', (_, layout, expected) => {
        const { container, scrollers } = mountTrace(layout)

        revealFirstOpenMessage(container, 'align')

        expect(scrolled(scrollers)).toEqual(expected)
    })
})

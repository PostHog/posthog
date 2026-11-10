import { type TileCarry, type TilePickUp, carryTile, getTilePickUp } from './carryTile'

const HANDLE = '.CardMeta,.drag-handle'
const CANCEL = 'a,table,button,input,.Popover'

function renderGrid(): {
    grid: HTMLElement
    meta: HTMLElement
    button: HTMLElement
    body: HTMLElement
} {
    document.body.innerHTML = `
        <div class="react-grid-layout">
            <div class="react-grid-item">
                <div class="CardMeta">
                    <span class="title">Signups</span><button>More</button>
                </div>
                <div class="body">chart</div>
            </div>
        </div>`
    return {
        grid: document.querySelector('.react-grid-layout')!,
        meta: document.querySelector('.title')!,
        button: document.querySelector('button')!,
        body: document.querySelector('.body')!,
    }
}

function clickOn(target: Element, init: MouseEventInit = {}): MouseEvent {
    const event = new MouseEvent('click', { bubbles: true, cancelable: true, clientX: 10, clientY: 10, ...init })
    target.dispatchEvent(event)
    return event
}

describe('carryTile', () => {
    let listeners: AbortController
    let carries: TileCarry[]

    const listen = <K extends keyof DocumentEventMap>(
        target: EventTarget,
        type: K,
        handler: (event: DocumentEventMap[K]) => unknown
    ): void => target.addEventListener(type, handler as EventListener, { signal: listeners.signal })

    const startCarry = (props: Parameters<typeof carryTile>[0]): TileCarry => {
        const carry = carryTile(props)
        carries.push(carry)
        return carry
    }

    beforeEach(() => {
        jest.useFakeTimers()
        listeners = new AbortController()
        carries = []
    })

    afterEach(() => {
        carries.forEach((carry) => carry.cancel())
        listeners.abort()
        jest.runOnlyPendingTimers()
        jest.useRealTimers()
        document.body.innerHTML = ''
    })

    test.each([
        ['an unmoved click on the drag handle', 'meta', { x: 10, y: 10 }, {}, true],
        ['a click on the chart, outside the drag handle', 'body', { x: 10, y: 10 }, {}, false],
        ['a button inside the drag handle', 'button', { x: 10, y: 10 }, {}, false],
        ['the end of a held drag', 'meta', { x: 40, y: 10 }, {}, false],
    ] as const)('decides whether %s picks up the tile', (_, targetKey, press, init, expected) => {
        const elements = renderGrid()
        const result: { pickUp: TilePickUp | null } = { pickUp: null }
        listen(elements[targetKey], 'click', (event) => {
            result.pickUp = getTilePickUp(event, press, HANDLE, CANCEL)
        })
        clickOn(elements[targetKey], init)
        expect(result.pickUp?.target ?? null).toBe(expected ? elements[targetKey] : null)
    })

    it('ends the drag on the next release and swallows the click that follows it', () => {
        const { grid, meta, body } = renderGrid()
        const presses: number[] = []
        listen(meta, 'mousedown', (event) => presses.push(event.buttons))
        const releases: number[] = []
        listen(document, 'mouseup', (event) => releases.push(event.clientX))
        const onDrop = jest.fn()

        startCarry({ target: meta, grid, clientX: 10, clientY: 10, onDrop, onCancel: jest.fn() })
        expect(presses).toEqual([1])

        const dropPress = new MouseEvent('mousedown', { bubbles: true, cancelable: true, button: 0 })
        body.dispatchEvent(dropPress)
        body.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, button: 0, clientX: 300 }))
        const dropClick = clickOn(body)

        expect(dropPress.defaultPrevented).toBe(true)
        expect(releases).toEqual([300])
        expect(onDrop).toHaveBeenCalledTimes(1)
        expect(dropClick.defaultPrevented).toBe(true)

        jest.runAllTimers()
        expect(clickOn(body).defaultPrevented).toBe(false)
    })

    it('keeps a held drag going after its release, until the next click', () => {
        const { grid, meta, body } = renderGrid()
        const presses: number[] = []
        listen(meta, 'mousedown', (event) => presses.push(event.buttons))
        const releases: number[] = []
        listen(document, 'mouseup', (event) => releases.push(event.clientX))
        const onDrop = jest.fn()

        startCarry({ target: meta, grid, clientX: 10, clientY: 10, held: true, onDrop, onCancel: jest.fn() })
        body.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, button: 0, clientX: 100 }))

        expect(presses).toEqual([])
        expect(releases).toEqual([])
        expect(onDrop).not.toHaveBeenCalled()

        body.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, button: 0 }))
        body.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, button: 0, clientX: 300 }))

        expect(releases).toEqual([300])
        expect(onDrop).toHaveBeenCalledTimes(1)
    })

    it('replays the last pointer position on scroll until the tile is dropped', () => {
        const { grid, meta, body } = renderGrid()
        const moves: [number, number][] = []
        listen(document, 'mousemove', (event) => moves.push([event.clientX, event.clientY]))

        startCarry({ target: meta, grid, clientX: 10, clientY: 10, onDrop: jest.fn(), onCancel: jest.fn() })
        body.dispatchEvent(new MouseEvent('mousemove', { bubbles: true, clientX: 40, clientY: 60 }))
        body.dispatchEvent(new Event('scroll'))
        expect(moves).toEqual([
            [40, 60],
            [40, 60],
        ])

        body.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, button: 0 }))
        body.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, button: 0 }))
        body.dispatchEvent(new Event('scroll'))
        expect(moves).toHaveLength(2)
    })

    it('puts the tile back on Esc by releasing at the pick-up point', () => {
        const { grid, meta } = renderGrid()
        const pointer: [string, number, number][] = []
        const record = (event: MouseEvent): number => pointer.push([event.type, event.clientX, event.clientY])
        listen(document, 'mousemove', record)
        listen(document, 'mouseup', record)
        const onCancel = jest.fn()
        const onDrop = jest.fn()

        startCarry({ target: meta, grid, clientX: 25, clientY: 40, onDrop, onCancel })
        window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))

        expect(onCancel).toHaveBeenCalledTimes(1)
        expect(onDrop).not.toHaveBeenCalled()
        expect(pointer).toEqual([
            ['mousemove', 25, 40],
            ['mouseup', 25, 40],
        ])
    })
})

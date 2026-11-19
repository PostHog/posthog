import type { MouseEvent } from 'react'

import { pulseOpenHandlers } from './todayPulseOpenHandlers'

describe('pulseOpenHandlers', () => {
    const event = (fields: Partial<MouseEvent<HTMLElement>>): MouseEvent<HTMLElement> =>
        ({ button: 0, metaKey: false, ctrlKey: false, ...fields }) as MouseEvent<HTMLElement>

    it.each([
        ['a plain click', 'onClick', event({}), 1],
        ['a Cmd-click', 'onMouseDown', event({ metaKey: true }), 1],
        ['a Ctrl-click', 'onMouseDown', event({ ctrlKey: true }), 1],
        ['a middle click', 'onAuxClick', event({ button: 1 }), 1],
        ['a plain mouse down, which the click already counts', 'onMouseDown', event({}), 0],
        ['a right click', 'onAuxClick', event({ button: 2 }), 0],
    ] as const)('records %s as many times as it opens the link', (_name, handler, mouseEvent, expected) => {
        const onOpen = jest.fn()
        const handlers = pulseOpenHandlers(onOpen)
        if (handler === 'onClick') {
            handlers.onClick()
        } else {
            handlers[handler](mouseEvent)
        }
        expect(onOpen).toHaveBeenCalledTimes(expected)
    })
})

/**
 * @jest-environment jsdom
 */
import type { Replayer } from 'posthog-js/rrweb'

import { resetClickIndicatorAfterFlash } from './click-indicator'

describe('resetClickIndicatorAfterFlash', () => {
    function mountCursor(): { replayer: Replayer; cursor: HTMLElement } {
        const wrapper = document.createElement('div')
        const cursor = document.createElement('div')
        cursor.classList.add('replayer-mouse', 'active')
        wrapper.appendChild(cursor)
        return { replayer: { wrapper } as Replayer, cursor }
    }

    it.each(['animationend', 'animationcancel'])('clears the active class on %s', (eventName) => {
        const { replayer, cursor } = mountCursor()
        resetClickIndicatorAfterFlash(replayer)

        cursor.dispatchEvent(new Event(eventName))

        expect(cursor.classList.contains('active')).toBe(false)
    })

    it('stops clearing the active class once disposed', () => {
        const { replayer, cursor } = mountCursor()
        const dispose = resetClickIndicatorAfterFlash(replayer)

        dispose()
        cursor.dispatchEvent(new Event('animationend'))

        expect(cursor.classList.contains('active')).toBe(true)
    })
})

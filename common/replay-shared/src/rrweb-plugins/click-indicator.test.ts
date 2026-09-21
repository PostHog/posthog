/**
 * @jest-environment jsdom
 */
import { Replayer } from 'posthog-js/rrweb'

import { resetClickIndicatorAfterFlash } from './index'

// posthog-js/* ships ESM that the test transform can't load directly; these values are
// only used by sibling plugins, not by the helper under test.
jest.mock('posthog-js/rrweb', () => ({
    Replayer: jest.fn(),
    canvasMutation: jest.fn(),
}))
jest.mock('posthog-js/rrweb-types', () => ({
    EventType: {},
    IncrementalSource: {},
}))

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

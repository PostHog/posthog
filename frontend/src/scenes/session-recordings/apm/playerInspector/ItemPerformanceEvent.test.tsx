import { render } from '@testing-library/react'

import { BodyDisplay, isFailedNetworkRequest } from 'scenes/session-recordings/apm/playerInspector/ItemPerformanceEvent'

import { PerformanceEvent } from '~/types'

describe('ItemPerformanceEvent', () => {
    it.each([
        ['[SessionReplay] Timeout while trying to read body', 'took too long'],
        ['[SessionReplay] Body too large to record (> 1000000 bytes)', 'too large'],
        ['[SessionReplay] Cannot read body of type Blob', "type isn't supported"],
        ['[SessionReplay] Failed to stringify response object', "couldn't be converted to text"],
        ['[SessionReplay] Failed to read body: AbortError', "couldn't read this body"],
        ['[SessionReplay] Some new message we do not map yet', "couldn't record this body"],
    ])('BodyDisplay explains the SDK diagnostic %s', (content, expectedExplanation) => {
        const { container } = render(<BodyDisplay content={content} headers={undefined} />)
        expect(container.textContent).toContain(expectedExplanation)
        // the raw SDK string stays visible for anyone who needs it
        expect(container.textContent).toContain(content)
    })

    it.each([
        ['a fetch that threw has no status', { initiator_type: 'fetch', response_status: undefined }, true],
        [
            'a successful opaque cross-origin fetch reports status 0',
            { initiator_type: 'fetch', response_status: 0 },
            false,
        ],
        ['a failed XHR reports status 0', { initiator_type: 'xmlhttprequest', response_status: 0 }, true],
        ['a successful XHR keeps its real status', { initiator_type: 'xmlhttprequest', response_status: 200 }, false],
        ['a navigation is never a failed request', { entry_type: 'navigation', response_status: undefined }, false],
        [
            'a request captured before PostHog started is skipped',
            { is_initial: true, response_status: undefined },
            false,
        ],
        [
            'a resource-timing entry without a method is skipped',
            { method: undefined, response_status: undefined },
            false,
        ],
    ])('isFailedNetworkRequest: %s', (_desc, overrides, expected) => {
        const item = { entry_type: 'resource', method: 'GET', ...overrides } as PerformanceEvent
        expect(isFailedNetworkRequest(item)).toBe(expected)
    })
})

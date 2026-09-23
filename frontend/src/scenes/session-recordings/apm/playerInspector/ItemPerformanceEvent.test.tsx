import { render } from '@testing-library/react'

import {
    BodyDisplay,
    hasNoRecordedResponse,
    StatusTag,
} from 'scenes/session-recordings/apm/playerInspector/ItemPerformanceEvent'

import { PerformanceEvent } from '~/types'

describe('ItemPerformanceEvent', () => {
    it.each([
        ['[SessionReplay] Timeout while trying to read body', 'took too long'],
        ['[SessionReplay] Body too large to record (> 1000000 bytes)', 'too large'],
        ['[SessionReplay] Cannot read body of type Blob', "type isn't supported"],
        ['[SessionReplay] Failed to stringify response object', "couldn't be converted to text"],
        ['[SessionReplay] Failed to read body: AbortError', "couldn't read this body"],
        ['[SessionReplay] Some new message we do not map yet', "couldn't record this body"],
        // the SDK writes these three without a prefix
        ['Chunked Transfer-Encoding is not supported', 'chunked transfer encoding'],
        ['Content-Type video/mp4 is not supported', 'this content type'],
        ['api.company.com is in deny list', 'on your deny list'],
    ])('BodyDisplay explains the SDK diagnostic %s', (content, expectedExplanation) => {
        const { container } = render(<BodyDisplay content={content} headers={undefined} />)
        expect(container.textContent).toContain(expectedExplanation)
        // the raw SDK string stays visible for anyone who needs it
        expect(container.textContent).toContain(content)
    })

    it.each([
        [
            'a fetch that threw or was aborted has no status',
            { initiator_type: 'fetch', response_status: undefined },
            true,
        ],
        [
            'a successful opaque cross-origin fetch reports status 0',
            { initiator_type: 'fetch', response_status: 0 },
            false,
        ],
        ['an XHR with no response reports status 0', { initiator_type: 'xmlhttprequest', response_status: 0 }, true],
        ['a successful XHR keeps its real status', { initiator_type: 'xmlhttprequest', response_status: 200 }, false],
        ['a navigation never counts', { entry_type: 'navigation', response_status: undefined }, false],
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
    ])('hasNoRecordedResponse: %s', (_desc, overrides, expected) => {
        const item = { entry_type: 'resource', method: 'GET', ...overrides } as PerformanceEvent
        expect(hasNoRecordedResponse(item)).toBe(expected)
    })

    it.each([
        ['a fetch with no status', { initiator_type: 'fetch', response_status: undefined }],
        ['an XHR with status 0', { initiator_type: 'xmlhttprequest', response_status: 0 }],
    ])('StatusTag marks %s so the waterfall shows it too', (_desc, overrides) => {
        const item = { entry_type: 'resource', method: 'GET', ...overrides } as PerformanceEvent
        const { container } = render(<StatusTag item={item} detailed={false} />)
        expect(container.textContent).toContain('No response')
    })

    it.each([
        ['a 200 response', { initiator_type: 'fetch', response_status: 200 }],
        ['an opaque cross-origin fetch with status 0', { initiator_type: 'fetch', response_status: 0 }],
    ])('StatusTag does not mark %s', (_desc, overrides) => {
        const item = { entry_type: 'resource', method: 'GET', ...overrides } as PerformanceEvent
        const { container } = render(<StatusTag item={item} detailed={false} />)
        expect(container.textContent).not.toContain('No response')
    })

    // an abort and a block are indistinguishable here, so the tag must not declare a failure
    it('hedges the cause when no response was recorded', () => {
        const item = { entry_type: 'resource', method: 'GET', initiator_type: 'fetch' } as PerformanceEvent
        const { container } = render(<StatusTag item={item} detailed={true} />)
        expect(container.querySelector('.LemonTag')?.textContent).toEqual('No response')
        expect(container.textContent).toContain('blocked, failed, or cancelled')
    })
})

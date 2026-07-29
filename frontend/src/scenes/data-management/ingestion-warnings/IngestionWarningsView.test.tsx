import '@testing-library/jest-dom'

import { render } from '@testing-library/react'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'

import type { IngestionWarning } from './ingestionWarningsLogic'
import { WARNING_TYPE_RENDERER } from './IngestionWarningsView'

describe('IngestionWarningsView', () => {
    beforeEach(() => {
        initKeaTests()
    })

    const renderWarning = (details: Record<string, unknown>): { html: string; unmount: () => void } => {
        const warning = {
            type: 'client_ingestion_warning',
            timestamp: '2026-07-29T00:00:00Z',
            details,
        } as unknown as IngestionWarning
        const { container, unmount } = render(
            <Provider>{WARNING_TYPE_RENDERER.client_ingestion_warning(warning)}</Provider>
        )
        return { html: container.innerHTML, unmount }
    }

    it('surfaces the message an SDK reported', () => {
        const { html, unmount } = renderWarning({
            message: 'Cannot call identify with a distinct_id of "undefined"',
            distinctId: '019f9c1f-aaaa-7000-8000-000000000000',
        })

        expect(html).toContain('Cannot call identify with a distinct_id of "undefined"')
        expect(html).toContain('019f9c1f-aaaa-7000-8000-000000000000')
        unmount()
    })

    // These details come off a publicly-ingestible event, so any field can hold arbitrary JSON.
    // Handing React a non-string child throws and takes the whole warnings table down.
    it.each([
        { name: 'an object message', details: { message: { nested: 'oops' } } },
        { name: 'an array message', details: { message: ['a', 'b'] } },
        { name: 'a numeric message', details: { message: 42 } },
        { name: 'an object distinctId', details: { message: 'ok', distinctId: { nested: 'oops' } } },
    ])('renders a fallback for $name instead of throwing', ({ details }) => {
        const { html, unmount } = renderWarning(details)

        expect(html).not.toContain('oops')
        unmount()
    })
})

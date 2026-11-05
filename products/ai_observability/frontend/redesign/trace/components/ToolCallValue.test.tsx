import { cleanup, render, waitFor } from '@testing-library/react'

import { ToolCallValue } from './ToolCallValue'

const longResult = { history: Array.from({ length: 6 }, (_, index) => ({ month: `2026-0${index + 1}`, seats: 4 })) }

describe('ToolCallValue', () => {
    afterEach(cleanup)

    test.each([
        ['shows a short value open, with no fold', { plan: 'team', seats: 6 }, null, { open: null, body: true }],
        ['folds a long value to one line, with no body', longResult, null, { open: false, body: false }],
        ['opens a folded value that shows the search query', longResult, '2026-05', { open: true, body: true }],
    ])('%s', async (_name, value, highlightQuery, expected) => {
        const { container } = render(<ToolCallValue value={value} highlightQuery={highlightQuery} />)

        await waitFor(() =>
            expect({
                open: container.querySelector('details')?.open ?? null,
                body: container.querySelector('dl') !== null,
            }).toEqual(expected)
        )
    })
})

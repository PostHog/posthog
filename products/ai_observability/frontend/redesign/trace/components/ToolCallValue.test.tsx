import { cleanup, render } from '@testing-library/react'

import { ToolCallValue } from './ToolCallValue'

const longResult = { history: Array.from({ length: 6 }, (_, index) => ({ month: `2026-0${index + 1}`, seats: 4 })) }

describe('ToolCallValue', () => {
    afterEach(cleanup)

    test.each([
        ['shows a short value open, with no fold', { plan: 'team', seats: 6 }, null, null],
        ['folds a long value', longResult, null, false],
        ['opens a folded value that shows the search query', longResult, '2026-05', true],
    ])('%s', (_name, value, highlightQuery, isOpen) => {
        const { container } = render(<ToolCallValue value={value} highlightQuery={highlightQuery} />)

        expect(container.querySelector('details')?.open ?? null).toBe(isOpen)
    })
})

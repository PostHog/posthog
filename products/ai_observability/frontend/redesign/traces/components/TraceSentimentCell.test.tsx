import { cleanup, render } from '@testing-library/react'

import type { TraceSentimentApi } from '../../../generated/api.schemas'
import type { TraceCellStatus } from '../../shared/cellLoads'
import { TraceSentimentCell } from './TraceSentimentCell'

describe('TraceSentimentCell', () => {
    afterEach(cleanup)

    it.each<[string, TraceSentimentApi | null, TraceCellStatus, string]>([
        ['a skeleton while loading', null, 'loading', 'Loading…'],
        ['the label with its score', { label: 'negative', score: 0.674 }, 'ready', 'Negative 67%'],
        ['a dash for no sentiment', null, 'ready', '-'],
        ['a failure mark when it could not load', null, 'error', ''],
    ])('renders %s', (_name, sentiment, status, shown) => {
        const { container } = render(<TraceSentimentCell sentiment={sentiment} status={status} />)

        expect(container.textContent).toBe(shown)
        expect(!!container.querySelector('[role="img"][aria-label^="Couldn\'t load"]')).toBe(status === 'error')
    })
})

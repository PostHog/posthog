import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { type TooltipContext } from '@posthog/quill-charts'

import { initKeaTests } from '~/test/init'

import { type SqlLineSeriesMeta } from './sqlLineGraphAdapter'
import { SqlLineGraphTooltip } from './SqlLineGraphTooltip'

const context = (overrides: Partial<TooltipContext<SqlLineSeriesMeta>> = {}): TooltipContext<SqlLineSeriesMeta> =>
    ({
        dataIndex: 0,
        label: '2024-01-01',
        seriesData: [
            {
                series: { key: 'a', label: 'Signups', data: [10], meta: { settings: undefined } },
                value: 10,
                color: '#111',
            },
            {
                series: { key: 'b', label: 'Logins', data: [5], meta: { settings: undefined } },
                value: 5,
                color: '#222',
            },
        ],
        position: { x: 0, y: 0 },
        hoverPosition: null,
        canvasBounds: {} as DOMRect,
        isPinned: false,
        ...overrides,
    }) as TooltipContext<SqlLineSeriesMeta>

describe('SqlLineGraphTooltip', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('renders the x-axis label, a row per series, and a total row', () => {
        render(<SqlLineGraphTooltip context={context()} chartSettings={{}} />)

        expect(screen.getByText('2024-01-01')).toBeInTheDocument()
        expect(screen.getByText('Signups')).toBeInTheDocument()
        expect(screen.getByText('Logins')).toBeInTheDocument()
        expect(screen.getByText('Total')).toBeInTheDocument()
        expect(screen.getByText('15')).toBeInTheDocument()
    })

    it('hides the close button until the tooltip is pinned', () => {
        const { container } = render(<SqlLineGraphTooltip context={context()} chartSettings={{}} />)

        expect(container.querySelector('.InsightTooltip__close')).not.toBeInTheDocument()
    })

    it('shows the close button when pinned and calls onUnpin on click', async () => {
        const onUnpin = jest.fn()
        const { container } = render(
            <SqlLineGraphTooltip context={context({ isPinned: true, onUnpin })} chartSettings={{}} />
        )

        const closeButton = container.querySelector('.InsightTooltip__close')
        expect(closeButton).toBeInTheDocument()

        await userEvent.click(closeButton!)
        expect(onUnpin).toHaveBeenCalledTimes(1)
    })
})

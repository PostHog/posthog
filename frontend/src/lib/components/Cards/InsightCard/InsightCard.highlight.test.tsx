import '@testing-library/jest-dom'

import { render } from '@testing-library/react'
import React from 'react'

import { NodeKind } from '~/queries/schema/schema-general'
import { DashboardPlacement, QueryBasedInsightModel } from '~/types'

import { InsightCard } from './InsightCard'

jest.mock('kea', () => {
    const React = jest.requireActual('react')
    return {
        ...jest.requireActual('kea'),
        BindLogic: ({ children }: { children: React.ReactNode }) => React.createElement(React.Fragment, null, children),
        useActions: () => ({ persistDisplayOptions: jest.fn() }),
        useValues: () => ({ theme: null, insightLoading: false, insightDataLoading: false }),
    }
})

jest.mock('@floating-ui/react', () => ({ useMergeRefs: () => jest.fn() }))
jest.mock('react-intersection-observer', () => ({ useInView: () => ({ ref: jest.fn(), inView: true }) }))
jest.mock('lib/hooks/usePageVisibility', () => ({ usePageVisibility: () => ({ isVisible: true }) }))
jest.mock('scenes/insights/EmptyStates', () => ({
    InsightErrorState: () => <div />,
    InsightLoadingState: () => <div />,
    InsightTimeoutState: () => <div />,
    InsightValidationError: () => <div />,
}))
jest.mock('~/exporter/exporterViewLogic', () => ({ isSharedView: () => false }))
jest.mock('~/layout/ErrorBoundary', () => ({
    ErrorBoundary: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))
jest.mock('~/queries/Query/Query', () => ({ Query: () => <div data-testid="query" /> }))
jest.mock('./InsightMeta', () => ({ InsightMeta: () => <div data-testid="insight-meta" /> }))

const insight = {
    id: 101,
    short_id: 'target',
    query: { kind: NodeKind.TrendsQuery },
    result: [],
} as unknown as QueryBasedInsightModel

describe('InsightCard highlight class', () => {
    it('forwards the dashboard reveal contract to the card root', () => {
        const { container } = render(
            <InsightCard
                insight={insight}
                placement={DashboardPlacement.Dashboard}
                className="ai-highlight-test"
                data-dashboard-tile-id="41"
                data-dashboard-tile-highlighted="true"
                tabIndex={-1}
            />
        )

        const card = container.querySelector('[data-attr="insight-card"]')
        expect(card).toHaveClass('DashboardTileCard', 'InsightCard', 'ai-highlight-test')
        expect(card).toHaveAttribute('data-dashboard-tile-id', '41')
        expect(card).toHaveAttribute('data-dashboard-tile-highlighted', 'true')
        expect(card).toHaveAttribute('tabindex', '-1')
    })

    it('removes the highlighted class when the highlight expires upstream', () => {
        const { container, rerender } = render(
            <InsightCard insight={insight} placement={DashboardPlacement.Dashboard} highlighted />
        )

        expect(container.querySelector('[data-attr="insight-card"]')).toHaveClass('InsightCard--highlighted')

        rerender(<InsightCard insight={insight} placement={DashboardPlacement.Dashboard} highlighted={false} />)

        expect(container.querySelector('[data-attr="insight-card"]')).not.toHaveClass('InsightCard--highlighted')
    })
})

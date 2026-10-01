import '@testing-library/jest-dom'

import { render } from '@testing-library/react'

import { NodeKind } from '~/queries/schema/schema-general'
import { InsightModel } from '~/types'

import { InsightIcon } from './SavedInsights'

describe('InsightIcon', () => {
    it.each([NodeKind.InsightVizNode, NodeKind.DataTableNode, NodeKind.DataVisualizationNode])(
        'renders nothing for a %s query without a source',
        (kind) => {
            const insight = { query: { kind } } as unknown as InsightModel

            const { container } = render(<InsightIcon insight={insight} />)

            expect(container).toBeEmptyDOMElement()
        }
    )

    it('renders the icon of the source query', () => {
        const insight = {
            query: { kind: NodeKind.InsightVizNode, source: { kind: NodeKind.TrendsQuery, series: [] } },
        } as unknown as InsightModel

        const { container } = render(<InsightIcon insight={insight} />)

        expect(container.querySelector('svg')).toBeInTheDocument()
    })
})

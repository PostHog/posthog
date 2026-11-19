import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { BIVisualizationNode } from '~/queries/schema/schema-business-intelligence'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { biDashboardCrossFilterLogic } from './biDashboardCrossFilterLogic'
import { BIDashboardFilterBar } from './BIDashboardFilterBar'
import { buildBIQuery, DEFAULT_BI_CONFIG } from './biEditorTypes'

describe('dashboard BI filter autocapture', () => {
    beforeEach(() => initKeaTests())
    afterEach(cleanup)

    it.each([false, true])('excludes the summary and portaled selection details (quill=%s)', async (quill) => {
        featureFlagLogic.actions.setFeatureFlags([], { 'today-rail-nav': quill })
        const config = {
            ...DEFAULT_BI_CONFIG,
            source: { table: 'example_orders' },
            rows: [
                {
                    id: 'country',
                    name: 'Country',
                    expression: 'country',
                    type: 'string' as const,
                    source: { table: 'example_orders' },
                },
            ],
        }
        const query: BIVisualizationNode = {
            ...buildBIQuery(config)!.node,
            kind: NodeKind.BIVisualizationNode,
            config,
        }
        const logic = biDashboardCrossFilterLogic({ dashboardId: 777 })
        const unmount = logic.mount()
        try {
            logic.actions.selectMark(1, 'Example orders', query, { country: 'US' })
            const { container } = render(<BIDashboardFilterBar dashboardId={777} />)
            const summary = screen.getByLabelText('BI filter: Country: US')
            expect(summary.closest('.ph-no-capture')).not.toBeNull()

            await userEvent.click(summary)
            const value = await screen.findByText('Country: US', { exact: true })
            const source = screen.getByText('Example orders')
            expect(container).not.toContainElement(value)
            expect(value.closest('.ph-no-capture')).not.toBeNull()
            expect(source.closest('.ph-no-capture')).not.toBeNull()
        } finally {
            unmount()
        }
    })
})

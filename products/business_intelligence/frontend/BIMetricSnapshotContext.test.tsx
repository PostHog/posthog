import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { catalogMetricWorksheet } from './biCatalog'
import { BIMetricSnapshotContext } from './BIMetricSnapshotContext'

afterEach(cleanup)

it.each([
    ['approved', false, 'Approved'],
    ['proposed', false, 'Proposed'],
    ['approved', true, 'Drifted'],
] as const)('labels %s, drifted=%s as unverified catalog context', (status, is_drifted, label) => {
    initKeaTests()
    const config = catalogMetricWorksheet({
        id: 'example-metric',
        name: 'revenue',
        status,
        is_drifted,
        unit: 'usd',
        owner: 'analyst@example.com',
        definition: { kind: NodeKind.HogQLQuery, query: 'SELECT 42' },
    })!.config
    const view = render(<BIMetricSnapshotContext config={config} />)
    expect(screen.getByText('Catalog status when copied (unverified):')).toBeInTheDocument()
    expect(screen.getByText(label)).toBeInTheDocument()
    expect(screen.getByText('Unit: usd')).toBeInTheDocument()
    expect(screen.getByText('Owner: analyst@example.com')).toBeInTheDocument()
    expect(
        screen.getByText('These saved details are unverified. Check the current catalog entry before using this copy.')
    ).toBeInTheDocument()
    expect(view.container.querySelector('.LemonTag--success')).not.toBeInTheDocument()
    view.rerender(<BIMetricSnapshotContext config={{ ...config, catalogMetricContext: undefined }} />)
    expect(screen.queryByText('Approved')).not.toBeInTheDocument()
    expect(screen.getByText('Catalog status was not recorded for this copy.')).toBeInTheDocument()
})

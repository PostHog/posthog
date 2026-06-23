import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'

import { DashboardsContent } from './DashboardsContent'

jest.mock('./DashboardsTable', () => ({ DashboardsTableContainer: () => <div>table-arm</div> }))
jest.mock('./DashboardsExplorer', () => ({ DashboardsExplorer: () => <div>explorer-arm</div> }))
jest.mock('kea', () => ({ ...jest.requireActual('kea'), useValues: jest.fn() }))

function renderWithFlag(value: string | undefined): void {
    ;(useValues as jest.Mock).mockReturnValue({
        featureFlags: value === undefined ? {} : { [FEATURE_FLAGS.DASHBOARDS_LIST_VIEW]: value },
    })
    render(<DashboardsContent />)
}

describe('DashboardsContent', () => {
    afterEach(cleanup)

    it.each([undefined, 'control', 'bogus', 'grid', 'finder', 'tree'])('renders the table for variant %p', (value) => {
        renderWithFlag(value)
        expect(screen.getByText('table-arm')).toBeInTheDocument()
        expect(screen.queryByText('explorer-arm')).not.toBeInTheDocument()
    })

    it('renders the explorer for the explorer variant', () => {
        renderWithFlag('explorer')
        expect(screen.getByText('explorer-arm')).toBeInTheDocument()
    })
})

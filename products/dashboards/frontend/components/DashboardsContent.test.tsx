import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'

import { DashboardsContent } from './DashboardsContent'

jest.mock('scenes/dashboard/dashboards/DashboardsTable', () => ({
    DashboardsTableContainer: () => <div>table-arm</div>,
}))
jest.mock('./DashboardsTree', () => ({ DashboardsTree: () => <div>tree-arm</div> }))
jest.mock('kea', () => ({ ...jest.requireActual('kea'), useValues: jest.fn() }))

function renderWithFlag(value: string | undefined): void {
    ;(useValues as jest.Mock).mockReturnValue({
        featureFlags: value === undefined ? {} : { [FEATURE_FLAGS.DASHBOARDS_LIST_VIEW]: value },
    })
    render(<DashboardsContent />)
}

describe('DashboardsContent', () => {
    afterEach(cleanup)

    it.each([undefined, 'control', 'bogus', 'grid', 'finder', 'explorer'])(
        'renders the table for variant %p',
        (value) => {
            renderWithFlag(value)
            expect(screen.getByText('table-arm')).toBeInTheDocument()
            expect(screen.queryByText('tree-arm')).not.toBeInTheDocument()
        }
    )

    it('renders the tree for the tree variant', () => {
        renderWithFlag('tree')
        expect(screen.getByText('tree-arm')).toBeInTheDocument()
        expect(screen.queryByText('table-arm')).not.toBeInTheDocument()
    })
})

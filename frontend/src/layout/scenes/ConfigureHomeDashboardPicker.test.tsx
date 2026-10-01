import { render, screen } from '@testing-library/react'
import { useActions, useValues } from 'kea'

import { ConfigureHomeDashboardPicker } from './ConfigureHomeDashboardPicker'

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useActions: jest.fn(),
    useValues: jest.fn(),
}))

jest.mock('@posthog/lemon-ui', () => ({
    LemonSearchableSelect: ({ disabledReason }: { disabledReason?: string }) => (
        <button disabled={!!disabledReason}>{disabledReason || 'Ready'}</button>
    ),
}))

const mockedUseActions = useActions as jest.Mock
const mockedUseValues = useValues as jest.Mock

describe('ConfigureHomeDashboardPicker', () => {
    beforeEach(() => {
        mockedUseValues.mockReturnValueOnce({ nameSortedDashboards: [], dashboardsLoading: true })
        mockedUseValues.mockReturnValueOnce({ currentTeam: null })
        mockedUseActions.mockReturnValue({
            loadDashboardsIfNeeded: jest.fn(),
            setHomepage: jest.fn(),
            updateCurrentTeam: jest.fn(),
        })
    })

    it('disables selection until dashboards finish loading', () => {
        render(<ConfigureHomeDashboardPicker onSelect={jest.fn()} />)
        expect(screen.getByRole('button')).toHaveProperty('disabled', true)
        expect(screen.getByRole('button').textContent).toEqual('Loading dashboards…')
    })
})

import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { AccessControlLevel, DashboardPlacement, DashboardType, QueryBasedInsightModel } from '~/types'

import { DashboardPublicAccessBanner } from './DashboardPublicAccessBanner'

const MOCK_DASHBOARD: DashboardType<QueryBasedInsightModel> = {
    id: 5,
    name: 'Test dashboard',
    description: 'A test dashboard',
    pinned: false,
    tiles: [],
    tags: [],
    created_at: '2020-01-01T00:00:00Z',
    created_by: {
        id: 1,
        first_name: 'Test',
        last_name: 'User',
        email: 'test@posthog.com',
        uuid: 'abc',
        distinct_id: 'test-distinct-id',
    },
    last_accessed_at: '2020-01-01T00:00:00Z',
    is_shared: false,
    deleted: false,
    creation_mode: 'default',
    user_access_level: AccessControlLevel.Editor,
    filters: {},
    variables: {},
}

function makeDashboard(
    overrides: Partial<DashboardType<QueryBasedInsightModel>> = {}
): DashboardType<QueryBasedInsightModel> {
    return { ...MOCK_DASHBOARD, ...overrides }
}

function renderBanner({
    dashboard = makeDashboard({ is_shared: true }),
    placement = DashboardPlacement.Dashboard,
}: {
    dashboard?: DashboardType<QueryBasedInsightModel>
    placement?: DashboardPlacement
} = {}): void {
    render(<DashboardPublicAccessBanner dashboard={dashboard} placement={placement} />)
}

describe('DashboardPublicAccessBanner', () => {
    afterEach(() => {
        cleanup()
    })

    it('shows when a standard dashboard is shared publicly', async () => {
        renderBanner()

        expect(
            screen.getByText(
                'This dashboard is shared publicly. Updates you make here may be visible to anyone with the public link. Avoid adding sensitive data.'
            )
        ).toBeInTheDocument()
        expect(screen.getAllByText('Manage sharing')).toHaveLength(2)
    })

    it('shows for read-only team users', async () => {
        renderBanner({
            dashboard: makeDashboard({
                is_shared: true,
                user_access_level: AccessControlLevel.Viewer,
            }),
        })

        expect(screen.getByText(/This dashboard is shared publicly/)).toBeInTheDocument()
    })

    it('does not show when the dashboard is not shared', async () => {
        renderBanner({ dashboard: makeDashboard({ is_shared: false }) })

        expect(screen.queryByText(/This dashboard is shared publicly/)).not.toBeInTheDocument()
    })

    it.each([DashboardPlacement.Public, DashboardPlacement.Export])(
        'does not show for %s placement',
        async (placement) => {
            renderBanner({ placement })

            expect(screen.queryByText(/This dashboard is shared publicly/)).not.toBeInTheDocument()
        }
    )
})

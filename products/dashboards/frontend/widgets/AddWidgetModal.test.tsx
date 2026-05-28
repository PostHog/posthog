import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BindLogic } from 'kea'

import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel, DashboardType, QueryBasedInsightModel } from '~/types'

import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { AddWidgetModal } from './AddWidgetModal'

type AddWidgetModalProps = React.ComponentProps<typeof AddWidgetModal>

jest.mock('./previews/widgetPreviews', () => ({
    DASHBOARD_WIDGET_PREVIEWS: {
        error_tracking_list: () => <div data-attr="error-tracking-preview">Preview</div>,
    },
}))

const MOCK_DASHBOARD: DashboardType<QueryBasedInsightModel> = {
    id: 5,
    name: 'Test Dashboard',
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

function renderAddWidgetModal(props: Partial<AddWidgetModalProps> = {}): ReturnType<typeof dashboardLogic.build> {
    const logic = dashboardLogic({ id: MOCK_DASHBOARD.id, dashboard: MOCK_DASHBOARD })
    logic.mount()

    render(
        <BindLogic logic={dashboardLogic} props={{ id: MOCK_DASHBOARD.id, dashboard: MOCK_DASHBOARD }}>
            <AddWidgetModal isOpen onClose={jest.fn()} onAdd={jest.fn()} {...props} />
        </BindLogic>
    )

    return logic
}

describe('AddWidgetModal', () => {
    beforeEach(() => {
        initKeaTests(true, { ...MOCK_DEFAULT_TEAM, autocapture_exceptions_opt_in: false })
    })

    afterEach(() => {
        cleanup()
    })

    it('renders grouped widget options with section headings', () => {
        renderAddWidgetModal()

        expect(
            screen.getByText(/Bring context from your different PostHog products into one dashboard/i)
        ).toBeInTheDocument()
        expect(screen.getByRole('heading', { name: 'Error tracking' })).toBeInTheDocument()
        expect(screen.getByRole('checkbox', { name: 'Top issues' })).toBeInTheDocument()
        expect(screen.getByText(/Ranked list of the most impactful error tracking issues/i)).toBeInTheDocument()
    })

    it('allows multi-select checkbox behavior within grouped layout', async () => {
        renderAddWidgetModal()

        const topIssuesCard = screen.getByRole('checkbox', { name: 'Top issues' })

        expect(topIssuesCard).toHaveAttribute('aria-checked', 'false')

        await userEvent.click(topIssuesCard)
        expect(topIssuesCard).toHaveAttribute('aria-checked', 'true')

        await userEvent.click(topIssuesCard)
        expect(topIssuesCard).toHaveAttribute('aria-checked', 'false')
    })

    it('submits all selected widget types', async () => {
        const onAdd = jest.fn().mockResolvedValue(undefined)
        const onClose = jest.fn()

        renderAddWidgetModal({ onAdd, onClose })

        await userEvent.click(screen.getByRole('checkbox', { name: 'Top issues' }))
        await userEvent.click(screen.getByRole('button', { name: 'Add widget' }))

        expect(onAdd).toHaveBeenCalledWith([expect.objectContaining({ widgetType: 'error_tracking_list' })])
        expect(onClose).toHaveBeenCalled()
    })

    it('still shows previews when exception autocapture is disabled', () => {
        renderAddWidgetModal()

        expect(screen.getByTestId('error-tracking-preview')).toBeInTheDocument()
        expect(screen.queryByText("You haven't captured any exceptions")).not.toBeInTheDocument()
    })
})

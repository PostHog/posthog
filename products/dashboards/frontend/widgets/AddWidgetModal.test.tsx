import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BindLogic } from 'kea'

import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel, DashboardType, QueryBasedInsightModel } from '~/types'

import { AddWidgetModal } from './AddWidgetModal'

type AddWidgetModalProps = React.ComponentProps<typeof AddWidgetModal>

jest.mock('../widget_types/catalog', () => ({
    ...jest.requireActual('../widget_types/catalog'),
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
        expect(screen.getByText('Error tracking')).toBeInTheDocument()
        expect(screen.getByLabelText('Top issues')).toBeInTheDocument()
        expect(screen.getByText(/Ranked list of the most impactful error tracking issues/i)).toBeInTheDocument()
    })

    it('allows multi-select checkbox behavior within grouped layout', async () => {
        renderAddWidgetModal()

        const topIssuesCard = screen.getByLabelText('Top issues')

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

        await userEvent.click(screen.getByLabelText('Top issues'))
        // "Add widget" is also the modal title, so target the footer button's content span
        await userEvent.click(screen.getByText('Add widget', { selector: '.LemonButton__content' }))

        expect(onAdd).toHaveBeenCalledWith([expect.objectContaining({ widgetType: 'error_tracking_list' })])
        expect(onClose).toHaveBeenCalled()
    })

    it('still shows previews when exception autocapture is disabled', () => {
        renderAddWidgetModal()

        expect(screen.getByTestId('error-tracking-preview')).toBeInTheDocument()
        expect(screen.queryByText("You haven't captured any exceptions")).not.toBeInTheDocument()
    })

    it('shows a group-level product nudge when the setup requirement is unmet', () => {
        renderAddWidgetModal()

        expect(screen.getByText(/Explore error tracking/i).closest('a')).toHaveAttribute(
            'href',
            'https://posthog.com/docs/error-tracking'
        )
    })

    it('does not show the nudge once the setup requirement is met', () => {
        initKeaTests(true, { ...MOCK_DEFAULT_TEAM, autocapture_exceptions_opt_in: true })
        renderAddWidgetModal()

        expect(screen.queryByText(/Explore error tracking/i)).not.toBeInTheDocument()
    })

    it('does not nudge for product areas without a setup requirement', () => {
        renderAddWidgetModal()

        expect(screen.queryByText(/Explore experiments/i)).not.toBeInTheDocument()
    })

    it('collapses and expands a section when its header is clicked', async () => {
        renderAddWidgetModal()

        expect(screen.getByLabelText('Top issues')).toBeInTheDocument()

        await userEvent.click(screen.getByText('Error tracking'))
        expect(screen.queryByLabelText('Top issues')).not.toBeInTheDocument()

        await userEvent.click(screen.getByText('Error tracking'))
        expect(screen.getByLabelText('Top issues')).toBeInTheDocument()
    })

    it('resets collapsed sections when the modal is reopened', async () => {
        const logic = renderAddWidgetModal()

        await userEvent.click(screen.getByText('Error tracking'))
        expect(logic.values.addWidgetCollapsedGroups).toContain('error_tracking')

        logic.actions.setAddWidgetModalOpen(true)
        expect(logic.values.addWidgetCollapsedGroups).toEqual([])
    })
})

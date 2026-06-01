import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { dashboardWidgetMenusLogic } from 'lib/components/Cards/InsightCard/dashboardWidgetMenusLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'
import {
    DashboardPlacement,
    DashboardTile,
    PropertyFilterType,
    PropertyOperator,
    QueryBasedInsightModel,
} from '~/types'

import { DashboardWidgetItem } from './DashboardWidgetItem'

jest.mock('lib/utils/accessControlUtils', () => ({
    userHasAccess: () => true,
}))

jest.mock('../../widgets/registry', () => ({
    getDashboardWidgetDefinition: () => ({
        Component: () => <div>Widget body</div>,
        EditModal: ({
            isOpen,
            name,
            defaultTitle,
            description,
            onSaveMetadata: _onSaveMetadata,
        }: {
            isOpen: boolean
            name?: string
            defaultTitle?: string
            description?: string
            onSaveMetadata?: (metadata: { name?: string; description?: string }) => void
        }) =>
            isOpen ? (
                <div role="dialog" aria-label="Widget settings">
                    <input defaultValue={name} placeholder={defaultTitle} aria-label="Title" />
                    <textarea
                        defaultValue={description}
                        placeholder="Enter description (optional)"
                        onChange={() => undefined}
                    />
                </div>
            ) : null,
        productAccess: 'error_tracking',
    }),
}))

jest.mock('../../widget_types/catalog', () => ({
    getDashboardWidgetCatalogEntry: () => ({
        titleHref: '/error_tracking',
        headerLayout: 'dashboard_tile',
        groupLabel: 'Error tracking',
        label: 'Top issues',
        headerTitle: 'Top issues',
    }),
}))

const tile = {
    id: 1,
    show_description: true,
    widget: {
        id: '10',
        widget_type: 'error_tracking_list',
        name: 'My issues',
        description: 'Top errors this week',
        config: { limit: 10, dateRange: { date_from: '-7d' } },
        dashboard_tiles: [],
    },
} as unknown as DashboardTile<QueryBasedInsightModel>

const tileWithoutDescription = {
    ...tile,
    widget: {
        ...tile.widget!,
        description: '',
    },
} as DashboardTile<QueryBasedInsightModel>

describe('DashboardWidgetItem', () => {
    beforeEach(() => {
        initKeaTests(true, {
            ...MOCK_DEFAULT_TEAM,
            test_account_filters: [
                {
                    key: 'email',
                    value: '@posthog.com',
                    operator: PropertyOperator.NotIContains,
                    type: PropertyFilterType.Person,
                },
            ],
        })
        featureFlagLogic.mount()
        dashboardWidgetMenusLogic({
            instanceKey: 'widget-10',
            dashboardId: 99,
            dashboards: undefined,
            dashboard_tiles: [],
        }).mount()
    })

    afterEach(() => {
        cleanup()
        dashboardWidgetMenusLogic({
            instanceKey: 'widget-10',
            dashboardId: 99,
            dashboards: undefined,
            dashboard_tiles: [],
        }).unmount()
    })

    it('renders insight-style more menu with view, dashboard section, and refresh data', async () => {
        const onRefresh = jest.fn()
        render(
            <DashboardWidgetItem
                tile={tile}
                placement={DashboardPlacement.Dashboard}
                dashboardId={99}
                result={null}
                loading={false}
                lastFetchedAt={Date.now()}
                onRefresh={onRefresh}
                onUpdateConfig={jest.fn()}
                onUpdateMetadata={jest.fn()}
                toggleShowDescription={jest.fn()}
                showEditingControls
                onDuplicate={jest.fn()}
                onRemove={jest.fn()}
                onMoveToDashboard={jest.fn()}
                onCopyToDashboard={jest.fn()}
            />
        )

        await userEvent.click(screen.getByRole('button', { name: /more/i }))

        expect(screen.getByRole('link', { name: 'View' })).toHaveAttribute('href', '/error_tracking')
        expect(
            screen
                .getAllByRole('button', { name: 'Edit' })
                .find((button: HTMLElement) => button.classList.contains('LemonButton--full-width'))
        ).toBeTruthy()
        expect(screen.getByRole('button', { name: 'Duplicate' })).toBeInTheDocument()
        expect(screen.getByText('Dashboard')).toBeInTheDocument()
        expect(screen.getByRole('button', { name: 'Hide description' })).toBeInTheDocument()
        expect(screen.getByRole('button', { name: 'Remove from dashboard' })).toBeInTheDocument()
        const refreshTrigger = screen.getByRole('button', { name: /Refresh data/i })
        expect(refreshTrigger).toBeInTheDocument()
        expect(screen.getByText(/Last computed/i)).toBeInTheDocument()

        await userEvent.click(refreshTrigger)
        expect(onRefresh).toHaveBeenCalledTimes(1)
    })

    it('removes widget immediately without a confirmation dialog', async () => {
        const onRemove = jest.fn()
        const { container } = render(
            <DashboardWidgetItem
                tile={tile}
                placement={DashboardPlacement.Dashboard}
                dashboardId={99}
                result={null}
                loading={false}
                onRefresh={jest.fn()}
                onUpdateConfig={jest.fn()}
                onUpdateMetadata={jest.fn()}
                showEditingControls
                onRemove={onRemove}
            />
        )

        await userEvent.click(within(container).getByRole('button', { name: /more/i }))
        await userEvent.click(await screen.findByRole('button', { name: 'Remove from dashboard' }))

        expect(onRemove).toHaveBeenCalledTimes(1)
        expect(
            screen.queryByText('Are you sure you want to remove this widget from the dashboard?')
        ).not.toBeInTheDocument()
    })

    it('does not show inline description editor in edit mode when description is empty', () => {
        const { container } = render(
            <DashboardWidgetItem
                tile={tileWithoutDescription}
                placement={DashboardPlacement.Dashboard}
                dashboardId={99}
                result={null}
                loading={false}
                onRefresh={jest.fn()}
                onUpdateConfig={jest.fn()}
                onUpdateMetadata={jest.fn()}
                showEditingControls
            />
        )

        expect(container.querySelector('[data-attr="widget-card-description"]')).toBeNull()
    })

    it('opens widget settings from add description menu item', async () => {
        const toggleShowDescription = jest.fn()
        const { container } = render(
            <DashboardWidgetItem
                tile={{ ...tileWithoutDescription, show_description: false }}
                placement={DashboardPlacement.Dashboard}
                dashboardId={99}
                result={null}
                loading={false}
                onRefresh={jest.fn()}
                onUpdateConfig={jest.fn()}
                onUpdateMetadata={jest.fn()}
                toggleShowDescription={toggleShowDescription}
                showEditingControls
            />
        )

        await userEvent.click(within(container).getByRole('button', { name: /more/i }))
        await userEvent.click(screen.getByRole('button', { name: 'Add description' }))

        expect(toggleShowDescription).toHaveBeenCalledTimes(1)
        expect(await screen.findByRole('dialog', { name: 'Widget settings' })).toBeInTheDocument()
    })

    it('opens widget settings with title and description fields from edit menu', async () => {
        const { container } = render(
            <DashboardWidgetItem
                tile={tileWithoutDescription}
                placement={DashboardPlacement.Dashboard}
                dashboardId={99}
                result={null}
                loading={false}
                onRefresh={jest.fn()}
                onUpdateConfig={jest.fn()}
                onUpdateMetadata={jest.fn()}
                showEditingControls
            />
        )

        await userEvent.click(within(container).getByRole('button', { name: /more/i }))
        await waitFor(() => {
            expect(document.querySelector('[data-attr="dashboard-widget-edit"]')).toBeInTheDocument()
        })
        await userEvent.click(document.querySelector('[data-attr="dashboard-widget-edit"]') as HTMLElement)

        const dialog = await screen.findByRole('dialog', { name: 'Widget settings' })
        expect(within(dialog).getByPlaceholderText('Top issues')).toBeInTheDocument()
        expect(within(dialog).getByPlaceholderText('Enter description (optional)')).toBeInTheDocument()
    })

    it('does not render inline title editor in edit mode', () => {
        const { container } = render(
            <DashboardWidgetItem
                tile={tile}
                placement={DashboardPlacement.Dashboard}
                dashboardId={99}
                result={null}
                loading={false}
                onRefresh={jest.fn()}
                onUpdateConfig={jest.fn()}
                onUpdateMetadata={jest.fn()}
                showEditingControls
            />
        )

        expect(container.querySelector('[data-attr="widget-card-title"] .EditableField')).toBeNull()
        expect(container.querySelector('[data-attr="widget-card-title"]')).toHaveTextContent('My issues')
    })
})

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

import { getDashboardWidgetCatalogEntry, tryGetDashboardWidgetCatalogEntry } from '../../widget_types/catalog'
import { userHasDashboardWidgetProductAccess } from '../../widgetProductAccess'
import { DashboardWidgetItem } from './DashboardWidgetItem'

jest.mock('lib/utils/accessControlUtils', () => ({
    userHasAccess: () => true,
}))

jest.mock('../../widgetProductAccess', () => ({
    userHasDashboardWidgetProductAccess: jest.fn(() => true),
    userCanMutateErrorTrackingIssuesOnDashboard: jest.fn(() => true),
}))

jest.mock('../../widget_types/widgetAvailability', () => ({
    useWidgetAvailability: () => ({ isAvailable: true }),
}))

jest.mock('../../widgets/registry', () => ({
    getDashboardWidgetDefinition: () => ({
        Component: () => <div>Widget body</div>,
        TileFilters: () => <div data-attr="widget-tile-filters">filters</div>,
        EditModal: ({
            isOpen,
            name,
            defaultTitle,
            description,
        }: {
            isOpen: boolean
            name?: string
            defaultTitle?: string
            description?: string
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
    getDashboardWidgetCatalogEntry: jest.fn(() => ({
        titleHref: '/error_tracking',
        headerLayout: 'dashboard_tile',
        groupId: 'error_tracking',
        label: 'Top issues',
        headerTitle: 'Top issues',
    })),
    tryGetDashboardWidgetCatalogEntry: jest.fn(() => ({
        titleHref: '/error_tracking',
        headerLayout: 'dashboard_tile',
        groupId: 'error_tracking',
        label: 'Top issues',
        headerTitle: 'Top issues',
        headerMeta: { showWidgetType: true, showDateRange: true },
        sharedPlaceholder: {
            title: 'Top issues',
            message: 'Log in to PostHog to see which errors are affecting your users.',
        },
    })),
    getUnknownDashboardWidgetCatalogFallback: jest.fn((widgetType: string) => ({
        groupId: widgetType,
        label: widgetType,
        headerTitle: widgetType,
        headerLayout: 'dashboard_tile',
        headerMeta: { showWidgetType: true, showDateRange: true },
    })),
    getDashboardWidgetGroupLabel: () => 'Error tracking',
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
        jest.mocked(userHasDashboardWidgetProductAccess).mockReturnValue(true)
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

    it('does not render tile filters without product access', () => {
        jest.mocked(userHasDashboardWidgetProductAccess).mockReturnValue(false)

        const { container } = render(
            <DashboardWidgetItem
                tile={tile}
                placement={DashboardPlacement.Dashboard}
                dashboardId={99}
                result={null}
                loading={false}
                onRefresh={jest.fn()}
                onUpdateWidgetTile={jest.fn()}
                showEditingControls
            />
        )

        expect(container.querySelector('[data-attr="widget-tile-filters"]')).toBeNull()
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
                onUpdateWidgetTile={jest.fn()}
                toggleShowDescription={jest.fn()}
                showEditingControls
                onDuplicate={jest.fn()}
                onRemove={jest.fn()}
                onMoveToDashboard={jest.fn()}
                onCopyToDashboard={jest.fn()}
            />
        )

        await userEvent.click(screen.getByLabelText('more'))

        expect(screen.getByText('View').closest('a')).toHaveAttribute('href', '/project/997/error_tracking')
        expect(
            screen
                .getAllByText('Edit')
                .map((label) => label.closest('button'))
                .find((button) => button?.classList.contains('LemonButton--full-width'))
        ).toBeTruthy()
        expect(screen.getByText('Duplicate')).toBeInTheDocument()
        expect(screen.getByText('Dashboard')).toBeInTheDocument()
        expect(screen.getByText('Hide description')).toBeInTheDocument()
        expect(screen.getByText('Remove from dashboard')).toBeInTheDocument()
        const refreshTrigger = document.querySelector('[data-attr="dashboard-tile-refresh-data"]') as HTMLElement
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
                onUpdateWidgetTile={jest.fn()}
                showEditingControls
                onRemove={onRemove}
            />
        )

        await userEvent.click(within(container).getByLabelText('more'))
        await userEvent.click(await screen.findByText('Remove from dashboard'))

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
                onUpdateWidgetTile={jest.fn()}
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
                onUpdateWidgetTile={jest.fn()}
                toggleShowDescription={toggleShowDescription}
                showEditingControls
            />
        )

        await userEvent.click(within(container).getByLabelText('more'))
        await userEvent.click(screen.getByText('Add description'))

        expect(toggleShowDescription).toHaveBeenCalledTimes(1)
        expect(await screen.findByLabelText('Widget settings')).toBeInTheDocument()
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
                onUpdateWidgetTile={jest.fn()}
                showEditingControls
            />
        )

        await userEvent.click(within(container).getByLabelText('more'))
        await waitFor(() => {
            expect(document.querySelector('[data-attr="dashboard-widget-edit"]')).toBeInTheDocument()
        })
        await userEvent.click(document.querySelector('[data-attr="dashboard-widget-edit"]') as HTMLElement)

        const dialog = await screen.findByLabelText('Widget settings')
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
                onUpdateWidgetTile={jest.fn()}
                showEditingControls
            />
        )

        expect(container.querySelector('[data-attr="widget-card-title"] .EditableField')).toBeNull()
        expect(container.querySelector('[data-attr="widget-card-title"]')).toHaveTextContent('My issues')
    })

    it('shows shared dashboard placeholder on public placement instead of widget data', () => {
        const { container } = render(
            <DashboardWidgetItem
                tile={tile}
                placement={DashboardPlacement.Public}
                dashboardId={99}
                result={{ results: [{ id: '1' }] }}
                loading={false}
                onRefresh={jest.fn()}
            />
        )

        expect(within(container).getByText('My issues')).toBeInTheDocument()
        expect(screen.getByTestId('shared-dashboard-widget-placeholder')).toBeInTheDocument()
        expect(screen.getByText('Log in to PostHog to see which errors are affecting your users.')).toBeInTheDocument()
        expect(screen.queryByText('Widget body')).not.toBeInTheDocument()
    })

    it('contains unknown widget errors in the card body while keeping the header', () => {
        // The thrown render error is expected: React and jsdom both report it to
        // console.error before the error boundary contains it
        const consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation()
        const catalogEntryMock = getDashboardWidgetCatalogEntry as jest.Mock
        ;(tryGetDashboardWidgetCatalogEntry as jest.Mock).mockReturnValue(undefined)
        catalogEntryMock.mockImplementation(() => {
            throw new Error('Unknown dashboard widget type: session_replay_list')
        })

        const { container } = render(
            <DashboardWidgetItem
                tile={tile}
                placement={DashboardPlacement.Dashboard}
                dashboardId={99}
                result={null}
                loading={false}
                error="Unknown widget type: session_replay_list"
                onRefresh={jest.fn()}
                onRemove={jest.fn()}
                showEditingControls
            />
        )

        expect(within(container).getByText('My issues')).toBeInTheDocument()
        expect(within(container).getByText('An error has occurred')).toBeInTheDocument()
        expect(within(container).getByText(/Unknown dashboard widget type: session_replay_list/)).toBeInTheDocument()
        expect(within(container).queryByText('Refresh data')).not.toBeInTheDocument()

        ;(tryGetDashboardWidgetCatalogEntry as jest.Mock).mockReturnValue({
            titleHref: '/error_tracking',
            headerLayout: 'dashboard_tile',
            groupId: 'error_tracking',
            label: 'Top issues',
            headerTitle: 'Top issues',
            headerMeta: { showWidgetType: true, showDateRange: true },
        })
        catalogEntryMock.mockImplementation(() => ({
            titleHref: '/error_tracking',
            headerLayout: 'dashboard_tile',
            groupId: 'error_tracking',
            label: 'Top issues',
            headerTitle: 'Top issues',
        }))
        consoleErrorSpy.mockRestore()
    })
})

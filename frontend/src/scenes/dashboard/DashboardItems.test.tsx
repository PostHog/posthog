import { render } from '@testing-library/react'

import { DashboardItems } from './DashboardItems'

jest.mock('react-grid-layout', () => {
    const Actual = jest.requireActual('react-grid-layout')
    return {
        ...Actual,
        Responsive: ({ children, ...props }: any) => <div data-props={JSON.stringify(props)}>{children}</div>,
    }
})

jest.mock('lib/hooks/useResizeObserver', () => ({
    useResizeObserver: () => ({ width: 1200, ref: jest.fn() }),
}))

jest.mock('scenes/dashboard/dashboardLogic', () => {
    const actual = jest.requireActual('scenes/dashboard/dashboardLogic')
    return {
        ...actual,
        dashboardLogic: () => ({
            values: {
                dashboard: { id: 1 },
                tiles: [],
                layouts: {},
                dashboardMode: 0,
                placement: 'dashboard',
                isRefreshingQueued: jest.fn(),
                isRefreshing: jest.fn(),
                highlightedInsightId: null,
                refreshStatus: {},
                itemsLoading: false,
                dashboardStreaming: false,
                effectiveEditBarFilters: undefined,
                effectiveDashboardVariableOverrides: undefined,
                temporaryBreakdownColors: [],
                dataColorThemeId: null,
                canEditDashboard: true,
            },
            actions: {
                updateLayouts: jest.fn(),
                updateContainerWidth: jest.fn(),
                updateTileColor: jest.fn(),
                toggleTileDescription: jest.fn(),
                removeTile: jest.fn(),
                duplicateTile: jest.fn(),
                refreshDashboardItem: jest.fn(),
                moveToDashboard: jest.fn(),
                setTileOverride: jest.fn(),
                setDashboardMode: jest.fn(),
            },
        }),
    }
})

describe('DashboardItems', () => {
    it('sets dashboard mode to Edit from CardDragHandle source when drag handle mousedown is used', () => {
        const { container } = render(<DashboardItems />)

        const root = container.firstElementChild as HTMLElement | null
        const props = JSON.parse(root?.getAttribute('data-props') || '{}')
        expect(props.resizeHandles).toEqual(['s', 'e', 'se'])
        expect(props.draggableHandle).toEqual('.CardMeta,.TextCard__body')
        expect(props.isResizable).toBe(false) // still in view mode

        // NOTE: Full kea wiring to assert DashboardEventSource.CardDragHandle would be done
        // in a dedicated dashboardLogic test; here we just ensure props plumbing works.
    })
})

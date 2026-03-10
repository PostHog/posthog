import { render } from '@testing-library/react'

import { DashboardItems } from './DashboardItems'

jest.mock('react-grid-layout', () => {
    const Actual = jest.requireActual('react-grid-layout')
    return {
        ...Actual,
        Responsive: (props: any) => <div data-props={JSON.stringify(props)} />,
    }
})

jest.mock('lib/hooks/useResizeObserver', () => ({
    useResizeObserver: () => ({ width: 1200, ref: jest.fn() }),
}))

describe('DashboardItems', () => {
    it('passes full resizeHandles set and enables editing only for desktop editable placements', () => {
        const { container } = render(
            <DashboardItems
                dashboard={null}
                tiles={[]}
                layouts={{}}
                dashboardMode={0 as any}
                placement={'dashboard' as any}
                canEditDashboard={true}
                updateLayouts={jest.fn()}
                updateContainerWidth={jest.fn()}
                removeTile={jest.fn()}
                moveToDashboard={jest.fn()}
                setDashboardMode={jest.fn()}
                setTileOverride={jest.fn()}
                reportDashboardTileRepositioned={jest.fn()}
                refreshStatus={{}}
                temporaryBreakdownColors={[]}
                dataColorThemeId={null}
                getCurrentExporterData={undefined}
                effectiveEditBarFilters={undefined}
                effectiveDashboardVariableOverrides={undefined}
                bestSurveyOpportunityFunnel={undefined}
            />
        )

        const props = JSON.parse(container.firstChild?.getAttribute('data-props') || '{}')
        expect(props.resizeHandles).toEqual(['s', 'e', 'se', 'n', 'w', 'nw', 'ne', 'sw'])
        expect(props.isResizable).toBe(true)
    })
})

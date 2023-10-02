import './WebDashboard.scss'
import { BREAKPOINT_COLUMN_COUNTS, BREAKPOINTS } from 'scenes/dashboard/dashboardLogic'
import { Query } from '~/queries/Query/Query'
import { Responsive, WidthProvider } from 'react-grid-layout'
import { useValues } from 'kea'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

const ResponsiveGridLayout = WidthProvider(Responsive)
export const WebAnalyticsDashboard = (): JSX.Element => {
    const { tiles, layouts, gridRows } = useValues(webAnalyticsLogic)
    return (
        <ResponsiveGridLayout
            layouts={layouts}
            cols={BREAKPOINT_COLUMN_COUNTS}
            breakpoints={BREAKPOINTS}
            rowHeight={500}
            maxRows={gridRows}
        >
            {tiles.map(({ query, layout }) => (
                <div key={layout.i} className="web-dashboard-items-wrapper">
                    <Query query={query} readOnly={true} />
                </div>
            ))}
        </ResponsiveGridLayout>
    )
}

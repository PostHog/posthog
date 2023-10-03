import { Query } from '~/queries/Query/Query'
import { useValues } from 'kea'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

export const WebAnalyticsDashboard = (): JSX.Element => {
    const { tiles } = useValues(webAnalyticsLogic)
    return (
        <div className="grid grid-cols-12 gap-4">
            {tiles.map(({ query, layout }, i) => (
                <div
                    key={i}
                    className={`col-span-${layout.colSpan ?? 6} row-span-${
                        layout.rowSpan ?? 1
                    } min-h-100 flex flex-col`}
                >
                    <Query query={query} readOnly={true} />
                </div>
            ))}
        </div>
    )
}

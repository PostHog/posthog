import clsx from 'clsx'
import { useActions } from 'kea'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { humanFriendlyLargeNumber } from 'lib/utils'
import { ProductIntentContext } from 'lib/utils/product-intents'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { ErrorTrackingTile } from 'scenes/web-analytics/webAnalyticsLogic'

import { Query } from '~/queries/Query/Query'
import { QueryFeature } from '~/queries/nodes/DataTable/queryFeatures'
import { QueryContext, QueryContextColumnComponent } from '~/queries/types'
import { ErrorTrackingIssue } from '~/schema'
import { ProductKey } from '~/types'

export const CustomGroupTitleColumn: QueryContextColumnComponent = (props) => {
    const record = props.record as ErrorTrackingIssue

    return (
        <div className="group flex items-start gap-x-1.5">
            <LemonTableLink
                title={record.name || 'Unknown Type'}
                description={
                    <div className="deprecated-space-y-1">
                        <div className="line-clamp-1">{record.description}</div>
                        <div className="deprecated-space-x-1">
                            <TZLabel time={record.last_seen} className="border-b border-dotted" />
                        </div>
                    </div>
                }
                className="flex-1"
                to={urls.errorTrackingIssue(record.id)}
            />
        </div>
    )
}

const CountColumn = ({ record, columnName }: { record: unknown; columnName: string }): JSX.Element => {
    const aggregations = (record as ErrorTrackingIssue).aggregations!
    const count = aggregations[columnName as 'occurrences' | 'users']
    return <span className="text-lg font-medium">{humanFriendlyLargeNumber(count)}</span>
}

const context: QueryContext = {
    extraDataTableQueryFeatures: [QueryFeature.hideLoadNextButton],
    showOpenEditorButton: false,
    showQueryEditor: false,
    columns: {
        error: {
            width: '50%',
            render: CustomGroupTitleColumn,
        },
        users: {
            align: 'right',
            render: CountColumn,
        },
        occurrences: {
            align: 'right',
            render: CountColumn,
        },
    },
}

export const WebAnalyticsErrorTrackingTile = ({ tile }: { tile: ErrorTrackingTile }): JSX.Element => {
    const { layout, query } = tile
    const to = urls.errorTracking()
    const { addProductIntentForCrossSell } = useActions(teamLogic)

    return (
        <div
            className={clsx(
                'col-span-1 row-span-1 flex flex-col',
                layout.colSpanClassName ?? 'md:col-span-6',
                layout.rowSpanClassName ?? 'md:row-span-1',
                layout.orderWhenLargeClassName ?? 'xxl:order-12',
                layout.className
            )}
        >
            <h2 className="m-0 mb-3">Error tracking</h2>
            <div className="bg-surface-primary flex flex-1 flex-col rounded border px-1 py-2">
                <Query query={query} embedded={true} context={context} />
            </div>
            <div className="my-2 flex flex-row-reverse">
                <LemonButton
                    to={to}
                    icon={<IconOpenInNew />}
                    onClick={() => {
                        addProductIntentForCrossSell({
                            from: ProductKey.WEB_ANALYTICS,
                            to: ProductKey.ERROR_TRACKING,
                            intent_context: ProductIntentContext.WEB_ANALYTICS_ERRORS,
                        })
                    }}
                    size="small"
                    type="secondary"
                >
                    View all
                </LemonButton>
            </div>
        </div>
    )
}

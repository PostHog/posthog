import clsx from 'clsx'
import { useActions } from 'kea'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { humanFriendlyLargeNumber } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { ErrorTrackingTile } from 'scenes/web-analytics/common'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

import { Query } from '~/queries/Query/Query'
import { QueryFeature } from '~/queries/nodes/DataTable/queryFeatures'
import { ErrorTrackingIssue, ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { QueryContext, QueryContextColumnComponent } from '~/queries/types'

export const CustomGroupTitleColumn: QueryContextColumnComponent = (props) => {
    const record = props.record as ErrorTrackingIssue

    return (
        <div className="flex items-start gap-x-1.5 group">
            <LemonTableLink
                target="_blank"
                title={record.name || 'Unknown Type'}
                description={<div className="line-clamp-1">{record.description}</div>}
                className="flex"
                to={urls.errorTrackingIssue(record.id)}
            />
        </div>
    )
}

const LastSeenColumn = ({ record }: { record: unknown }): JSX.Element => {
    const last_seen = (record as ErrorTrackingIssue).last_seen
    return <TZLabel time={last_seen} className="border-dotted border-b" />
}

const CountColumn = ({ record, columnName }: { record: unknown; columnName: string }): JSX.Element => {
    const aggregations = (record as ErrorTrackingIssue).aggregations!
    const count = aggregations[columnName as 'occurrences' | 'users']
    return <>{humanFriendlyLargeNumber(count)}</>
}

const context: QueryContext = {
    extraDataTableQueryFeatures: [QueryFeature.hideLoadNextButton],
    showOpenEditorButton: false,
    showQueryEditor: false,
    columns: {
        error: {
            align: 'left',
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
        last_seen: {
            title: 'Last seen',
            align: 'right',
            render: LastSeenColumn,
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
            <div className="border rounded bg-surface-primary flex-1 flex flex-col py-2 px-1">
                <Query attachTo={webAnalyticsLogic} query={query} embedded={true} context={context} />
            </div>
            <div className="flex flex-row-reverse my-2">
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

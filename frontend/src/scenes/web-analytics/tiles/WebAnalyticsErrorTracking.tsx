import clsx from 'clsx'
import { TZLabel } from 'lib/components/TZLabel'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { stringifiedFingerprint } from 'scenes/error-tracking/utils'
import { urls } from 'scenes/urls'
import { ErrorTrackingTile } from 'scenes/web-analytics/webAnalyticsLogic'

import { QueryFeature } from '~/queries/nodes/DataTable/queryFeatures'
import { Query } from '~/queries/Query/Query'
import { ErrorTrackingGroup } from '~/queries/schema'
import { QueryContext, QueryContextColumnComponent } from '~/queries/types'

export const CustomGroupTitleColumn: QueryContextColumnComponent = (props) => {
    const record = props.record as ErrorTrackingGroup

    return (
        <div className="flex items-start space-x-1.5 group">
            <LemonTableLink
                title={record.exception_type || 'Unknown Type'}
                description={
                    <div className="space-y-1">
                        <div className="line-clamp-1">{record.description}</div>
                        <div className="space-x-1">
                            <TZLabel time={record.last_seen} className="border-dotted border-b" />
                        </div>
                    </div>
                }
                className="flex-1"
                to={urls.errorTrackingGroup(stringifiedFingerprint(record.fingerprint))}
            />
        </div>
    )
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
        },
        occurrences: {
            align: 'right',
        },
    },
}

export const WebAnalyticsErrorTrackingTile = ({ tile }: { tile: ErrorTrackingTile }): JSX.Element => {
    const { layout, query } = tile
    const to = urls.errorTracking()

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
            <div className="border rounded bg-bg-light flex-1 flex flex-col py-2 px-1">
                <Query query={query} embedded={true} context={context} />
            </div>
            <div className="flex flex-row-reverse my-2">
                <LemonButton to={to} icon={<IconOpenInNew />} size="small" type="secondary">
                    View all
                </LemonButton>
            </div>
        </div>
    )
}

import { TZLabel } from '@posthog/apps-common'
import { LemonSegmentedButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { useMemo } from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'
import { QueryContext, QueryContextColumnComponent, QueryContextColumnTitleComponent } from '~/queries/types'

import { ErrorTrackingFilters } from './ErrorTrackingFilters'
import { errorTrackingLogic } from './errorTrackingLogic'
import { errorTrackingSceneLogic } from './errorTrackingSceneLogic'
import { errorTrackingQuery } from './queries'

export const scene: SceneExport = {
    component: ErrorTrackingScene,
    logic: errorTrackingSceneLogic,
}

export function ErrorTrackingScene(): JSX.Element {
    const { order } = useValues(errorTrackingSceneLogic)
    const { dateRange, filterTestAccounts, filterGroup, sparklineSelectedPeriod } = useValues(errorTrackingLogic)

    const query = useMemo(
        () =>
            errorTrackingQuery({
                order,
                dateRange,
                filterTestAccounts,
                filterGroup,
                sparklineSelectedPeriod,
            }),
        [order, dateRange, filterTestAccounts, filterGroup, sparklineSelectedPeriod]
    )

    const context: QueryContext = {
        columns: {
            error: {
                width: '50%',
                render: CustomGroupTitleColumn,
            },
            volume: { renderTitle: CustomVolumeColumnHeader },
        },
        showOpenEditorButton: false,
    }

    return (
        <div className="space-y-4">
            <ErrorTrackingFilters />
            <Query query={query} context={context} />
        </div>
    )
}

const CustomVolumeColumnHeader: QueryContextColumnTitleComponent = ({ columnName }) => {
    const { sparklineSelectedPeriod, sparklineOptions: options } = useValues(errorTrackingLogic)
    const { setSparklineSelectedPeriod } = useActions(errorTrackingLogic)

    if (!sparklineSelectedPeriod) {
        return null
    }

    return (
        <div className="flex justify-between items-center min-w-64">
            <div>{columnName}</div>
            <LemonSegmentedButton
                size="xsmall"
                value={sparklineSelectedPeriod}
                options={options}
                onChange={(value) => setSparklineSelectedPeriod(value)}
            />
        </div>
    )
}

const CustomGroupTitleColumn: QueryContextColumnComponent = (props) => {
    const { value, record } = props

    const properties = JSON.parse(value as string)

    const FirstAndLastSeen = ({ record }: { record: any[] }): JSX.Element => {
        const [last_seen, first_seen] = record.slice(-2) as [string, string]

        return (
            <div className="space-x-1">
                <TZLabel time={first_seen} className="border-dotted border-b" />
                <span>|</span>
                <TZLabel time={last_seen} className="border-dotted border-b" />
            </div>
        )
    }

    return (
        <LemonTableLink
            title={properties.$exception_type}
            description={
                <div className="space-y-1">
                    <div className="line-clamp-1">{properties.$exception_message}</div>
                    <FirstAndLastSeen record={record as any[]} />
                </div>
            }
            to={urls.errorTrackingGroup(properties.$exception_type)}
        />
    )
}

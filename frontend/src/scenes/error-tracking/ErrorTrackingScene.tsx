import { TZLabel } from '@posthog/apps-common'
import { LemonSegmentedButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { useMemo } from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'
import { ErrorTrackingGroup } from '~/queries/schema'
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
    const { value, record } = props as { value: string; record: ErrorTrackingGroup }

    const properties = JSON.parse(value)

    return (
        <LemonTableLink
            title={properties.$exception_fingerprint}
            description={
                <div className="space-y-1">
                    <div className="line-clamp-1">{properties.$exception_message}</div>
                    <div className="space-x-1">
                        <TZLabel time={record.first_seen} className="border-dotted border-b" />
                        <span>|</span>
                        <TZLabel time={record.last_seen} className="border-dotted border-b" />
                    </div>
                </div>
            }
            to={urls.errorTrackingGroup(properties.$exception_fingerprint)}
        />
    )
}

import { TZLabel } from '@posthog/apps-common'
import { LemonSegmentedButton } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { MemberSelect } from 'lib/components/MemberSelect'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { Query } from '~/queries/Query/Query'
import { ErrorTrackingGroup } from '~/queries/schema'
import { QueryContext, QueryContextColumnComponent, QueryContextColumnTitleComponent } from '~/queries/types'
import { InsightLogicProps } from '~/types'

import { errorTrackingDataLogic } from './errorTrackingDataLogic'
import { ErrorTrackingFilters } from './ErrorTrackingFilters'
import { errorTrackingLogic } from './errorTrackingLogic'
import { errorTrackingSceneLogic } from './errorTrackingSceneLogic'

export const scene: SceneExport = {
    component: ErrorTrackingScene,
    logic: errorTrackingSceneLogic,
}

export function ErrorTrackingScene(): JSX.Element {
    const { query } = useValues(errorTrackingSceneLogic)

    const insightProps: InsightLogicProps = {
        dashboardItemId: 'new-ErrorTrackingQuery',
    }

    const context: QueryContext = {
        columns: {
            error: {
                width: '50%',
                render: CustomGroupTitleColumn,
            },
            volume: { renderTitle: CustomVolumeColumnHeader },
            assignee: { render: AssigneeColumn },
        },
        showOpenEditorButton: false,
        insightProps: insightProps,
        alwaysRefresh: true,
    }

    return (
        <BindLogic logic={errorTrackingDataLogic} props={{ query, key: insightVizDataNodeKey(insightProps) }}>
            <div className="space-y-4">
                <ErrorTrackingFilters />
                <Query query={query} context={context} />
            </div>
        </BindLogic>
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
    const record = props.record as ErrorTrackingGroup

    return (
        <LemonTableLink
            title={record.fingerprint}
            description={
                <div className="space-y-1">
                    <div className="line-clamp-1">{record.description}</div>
                    <div className="space-x-1">
                        <TZLabel time={record.first_seen} className="border-dotted border-b" />
                        <span>|</span>
                        <TZLabel time={record.last_seen} className="border-dotted border-b" />
                    </div>
                </div>
            }
            to={urls.errorTrackingGroup(record.fingerprint)}
        />
    )
}

const AssigneeColumn: QueryContextColumnComponent = (props) => {
    const { assignGroup } = useActions(errorTrackingDataLogic)

    const record = props.record as ErrorTrackingGroup

    return (
        <MemberSelect
            defaultLabel="Unassigned"
            value={record.assignee}
            onChange={(user) => {
                const assigneeId = user?.id || null
                assignGroup(props.recordIndex, assigneeId)
            }}
        />
    )
}

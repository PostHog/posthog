import { TZLabel } from '@posthog/apps-common'
import { LemonButton, LemonCheckbox, LemonDivider, LemonSegmentedButton } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { FeedbackNotice } from 'lib/components/FeedbackNotice'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { Query } from '~/queries/Query/Query'
import { ErrorTrackingGroup } from '~/queries/schema'
import { QueryContext, QueryContextColumnComponent, QueryContextColumnTitleComponent } from '~/queries/types'
import { InsightLogicProps } from '~/types'

import { AssigneeSelect } from './AssigneeSelect'
import { errorTrackingDataNodeLogic } from './errorTrackingDataNodeLogic'
import ErrorTrackingFilters from './ErrorTrackingFilters'
import { errorTrackingLogic } from './errorTrackingLogic'
import { errorTrackingSceneLogic } from './errorTrackingSceneLogic'
import { stringifiedFingerprint } from './utils'

export const scene: SceneExport = {
    component: ErrorTrackingScene,
    logic: errorTrackingSceneLogic,
}

export function ErrorTrackingScene(): JSX.Element {
    const { query, selectedRowIndexes } = useValues(errorTrackingSceneLogic)

    const insightProps: InsightLogicProps = {
        dashboardItemId: 'new-ErrorTrackingQuery',
    }

    const context: QueryContext = {
        columns: {
            error: {
                width: '50%',
                render: CustomGroupTitleColumn,
            },
            occurrences: { align: 'center' },
            sessions: { align: 'center' },
            users: { align: 'center' },
            volume: { renderTitle: CustomVolumeColumnHeader },
            assignee: { render: AssigneeColumn },
        },
        showOpenEditorButton: false,
        insightProps: insightProps,
        alwaysRefresh: true,
    }

    return (
        <BindLogic logic={errorTrackingDataNodeLogic} props={{ query, key: insightVizDataNodeKey(insightProps) }}>
            <FeedbackNotice text="Error tracking is in closed alpha. Thanks for taking part! We'd love to hear what you think." />
            <ErrorTrackingFilters.FilterGroup />
            <LemonDivider className="mt-2" />
            {selectedRowIndexes.length === 0 ? <ErrorTrackingFilters.Options /> : <ErrorTrackingActions />}
            <Query query={query} context={context} />
        </BindLogic>
    )
}

const ErrorTrackingActions = (): JSX.Element => {
    const { selectedRowIndexes } = useValues(errorTrackingSceneLogic)
    const { setSelectedRowIndexes } = useActions(errorTrackingSceneLogic)
    const { mergeGroups } = useActions(errorTrackingDataNodeLogic)

    return (
        <div className="sticky top-[var(--breadcrumbs-height-compact)] z-20 py-2 bg-bg-3000 flex space-x-1">
            <LemonButton type="secondary" size="small" onClick={() => setSelectedRowIndexes([])}>
                Unselect all
            </LemonButton>
            {selectedRowIndexes.length > 1 && (
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={() => {
                        mergeGroups(selectedRowIndexes)
                        setSelectedRowIndexes([])
                    }}
                >
                    Merge
                </LemonButton>
            )}
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
    const { selectedRowIndexes } = useValues(errorTrackingSceneLogic)
    const { setSelectedRowIndexes } = useActions(errorTrackingSceneLogic)

    const rowIndex = props.recordIndex
    const record = props.record as ErrorTrackingGroup

    const checked = selectedRowIndexes.includes(props.recordIndex)

    return (
        <div className="flex items-start space-x-1.5 group">
            <LemonCheckbox
                className={clsx('pt-1 group-hover:visible', !checked && 'invisible')}
                checked={checked}
                onChange={(newValue) => {
                    setSelectedRowIndexes(
                        newValue ? [...selectedRowIndexes, rowIndex] : selectedRowIndexes.filter((id) => id != rowIndex)
                    )
                }}
            />
            <LemonTableLink
                title={record.exception_type || 'Unknown Type'}
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
                className="flex-1"
                to={urls.errorTrackingGroup(stringifiedFingerprint(record.fingerprint))}
            />
        </div>
    )
}

const AssigneeColumn: QueryContextColumnComponent = (props) => {
    const { assignGroup } = useActions(errorTrackingDataNodeLogic)

    const record = props.record as ErrorTrackingGroup

    return (
        <div className="flex justify-center">
            <AssigneeSelect
                assignee={record.assignee}
                onChange={(assigneeId) => assignGroup(props.recordIndex, assigneeId)}
            />
        </div>
    )
}

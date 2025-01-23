import { IconGear } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonDivider, LemonSegmentedButton, Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { FeedbackNotice } from 'lib/components/FeedbackNotice'
import { PageHeader } from 'lib/components/PageHeader'
import { Sparkline } from 'lib/components/Sparkline'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { humanFriendlyLargeNumber } from 'lib/utils'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { Query } from '~/queries/Query/Query'
import { ErrorTrackingIssue } from '~/queries/schema'
import { QueryContext, QueryContextColumnComponent, QueryContextColumnTitleComponent } from '~/queries/types'
import { InsightLogicProps } from '~/types'

import { AlphaAccessScenePrompt } from './AlphaAccessScenePrompt'
import { AssigneeSelect } from './AssigneeSelect'
import { errorTrackingDataNodeLogic } from './errorTrackingDataNodeLogic'
import ErrorTrackingFilters from './ErrorTrackingFilters'
import { errorTrackingIssueSceneLogic } from './errorTrackingIssueSceneLogic'
import { errorTrackingLogic } from './errorTrackingLogic'
import { errorTrackingSceneLogic } from './errorTrackingSceneLogic'
import { sparklineLabels, sparklineLabelsDay, sparklineLabelsMonth } from './utils'

export const scene: SceneExport = {
    component: ErrorTrackingScene,
    logic: errorTrackingSceneLogic,
}

export function ErrorTrackingScene(): JSX.Element {
    const { query, selectedIssueIds } = useValues(errorTrackingSceneLogic)

    const insightProps: InsightLogicProps = {
        dashboardItemId: 'new-ErrorTrackingQuery',
    }

    const context: QueryContext = {
        columns: {
            error: {
                width: '50%',
                render: CustomGroupTitleColumn,
            },
            occurrences: { align: 'center', render: CountColumn },
            sessions: { align: 'center', render: SessionCountColumn },
            users: { align: 'center', render: CountColumn },
            volume: { renderTitle: VolumeColumnHeader, render: VolumeColumn },
            assignee: { render: AssigneeColumn },
        },
        showOpenEditorButton: false,
        insightProps: insightProps,
        emptyStateHeading: 'No issues found',
        emptyStateDetail: 'Try changing the date range, changing the filters or removing the assignee.',
    }

    return (
        <AlphaAccessScenePrompt>
            <BindLogic logic={errorTrackingDataNodeLogic} props={{ query, key: insightVizDataNodeKey(insightProps) }}>
                <Header />
                <FeedbackNotice text="Error tracking is currently in beta. Thanks for taking part! We'd love to hear what you think." />
                <ErrorTrackingFilters.FilterGroup>
                    <ErrorTrackingFilters.UniversalSearch />
                </ErrorTrackingFilters.FilterGroup>
                <LemonDivider className="mt-2" />
                {selectedIssueIds.length === 0 ? <ErrorTrackingFilters.Options /> : <ErrorTrackingActions />}
                <Query query={query} context={context} />
            </BindLogic>
        </AlphaAccessScenePrompt>
    )
}

const ErrorTrackingActions = (): JSX.Element => {
    const { selectedIssueIds } = useValues(errorTrackingSceneLogic)
    const { setSelectedIssueIds } = useActions(errorTrackingSceneLogic)
    const { mergeIssues } = useActions(errorTrackingDataNodeLogic)

    return (
        <div className="sticky top-[var(--breadcrumbs-height-compact)] z-20 py-2 bg-bg-3000 flex space-x-1">
            <LemonButton type="secondary" size="small" onClick={() => setSelectedIssueIds([])}>
                Unselect all
            </LemonButton>
            {selectedIssueIds.length > 1 && (
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={() => {
                        mergeIssues(selectedIssueIds)
                        setSelectedIssueIds([])
                    }}
                >
                    Merge
                </LemonButton>
            )}
        </div>
    )
}

const VolumeColumn: QueryContextColumnComponent = (props) => {
    const { sparklineSelectedPeriod, customSparklineConfig } = useValues(errorTrackingLogic)
    const record = props.record as ErrorTrackingIssue

    const [data, labels] =
        sparklineSelectedPeriod === '24h'
            ? [record.volumeDay, sparklineLabelsDay]
            : sparklineSelectedPeriod === '1m'
            ? [record.volumeMonth, sparklineLabelsMonth]
            : customSparklineConfig
            ? [record.customVolume, sparklineLabels(customSparklineConfig)]
            : [null, null]

    return data ? <Sparkline className="h-8" data={data} labels={labels} /> : null
}

const VolumeColumnHeader: QueryContextColumnTitleComponent = ({ columnName }) => {
    const { sparklineSelectedPeriod: period, sparklineOptions: options } = useValues(errorTrackingLogic)
    const { setSparklineSelectedPeriod: onChange } = useActions(errorTrackingLogic)

    return period ? (
        <div className="flex justify-between items-center min-w-64">
            <div>{columnName}</div>
            <LemonSegmentedButton size="xsmall" value={period} options={options} onChange={onChange} />
        </div>
    ) : null
}

const CustomGroupTitleColumn: QueryContextColumnComponent = (props) => {
    const { selectedIssueIds } = useValues(errorTrackingSceneLogic)
    const { setSelectedIssueIds } = useActions(errorTrackingSceneLogic)

    const record = props.record as ErrorTrackingIssue

    const checked = selectedIssueIds.includes(record.id)

    return (
        <div className="flex items-start space-x-1.5 group">
            <LemonCheckbox
                className={clsx('pt-1 group-hover:visible', !checked && 'invisible')}
                checked={checked}
                onChange={(newValue) => {
                    setSelectedIssueIds(
                        newValue
                            ? [...new Set([...selectedIssueIds, record.id])]
                            : selectedIssueIds.filter((id) => id != record.id)
                    )
                }}
            />
            <LemonTableLink
                title={record.name || 'Unknown Type'}
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
                to={urls.errorTrackingIssue(record.id)}
                onClick={() => {
                    const issueLogic = errorTrackingIssueSceneLogic({ id: record.id })
                    issueLogic.mount()
                    issueLogic.actions.setIssue(record)
                }}
            />
        </div>
    )
}

const SessionCountColumn: QueryContextColumnComponent = ({ children, ...props }) => {
    const count = props.value as number
    return count === 0 ? (
        <Tooltip title="No $session_id was set for any event in this issue" delayMs={0}>
            -
        </Tooltip>
    ) : (
        <CountColumn {...props} />
    )
}

const CountColumn: QueryContextColumnComponent = ({ value }) => {
    return <>{humanFriendlyLargeNumber(value as number)}</>
}

const AssigneeColumn: QueryContextColumnComponent = (props) => {
    const { assignIssue } = useActions(errorTrackingDataNodeLogic)

    const record = props.record as ErrorTrackingIssue

    return (
        <div className="flex justify-center">
            <AssigneeSelect assignee={record.assignee} onChange={(assignee) => assignIssue(record.id, assignee)} />
        </div>
    )
}

const Header = (): JSX.Element => {
    const { user } = useValues(userLogic)

    return (
        <PageHeader
            buttons={
                <>
                    {user?.is_staff ? (
                        <LemonButton
                            onClick={() => {
                                throw Error('Oh my!')
                            }}
                        >
                            Send an exception
                        </LemonButton>
                    ) : null}
                    <LemonButton to="https://posthog.com/docs/error-tracking" type="secondary" targetBlank>
                        Documentation
                    </LemonButton>
                    <LemonButton to={urls.errorTrackingConfiguration()} type="secondary" icon={<IconGear />}>
                        Configure
                    </LemonButton>
                </>
            }
        />
    )
}

import { IconGear } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCheckbox,
    LemonDivider,
    LemonSegmentedButton,
    LemonSkeleton,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { FeedbackNotice } from 'lib/components/FeedbackNotice'
import { PageHeader } from 'lib/components/PageHeader'
import { Sparkline } from 'lib/components/Sparkline'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { humanFriendlyLargeNumber } from 'lib/utils'
import { posthog } from 'posthog-js'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { Query } from '~/queries/Query/Query'
import { ErrorTrackingIssue, ErrorTrackingIssueAggregations } from '~/queries/schema/schema-general'
import { QueryContext, QueryContextColumnComponent, QueryContextColumnTitleComponent } from '~/queries/types'
import { InsightLogicProps } from '~/types'

import { AssigneeSelect } from './AssigneeSelect'
import { errorTrackingDataNodeLogic } from './errorTrackingDataNodeLogic'
import { ErrorTrackingFilters } from './ErrorTrackingFilters'
import { errorTrackingIssueSceneLogic } from './errorTrackingIssueSceneLogic'
import { ErrorTrackingListOptions } from './ErrorTrackingListOptions'
import { errorTrackingLogic } from './errorTrackingLogic'
import { errorTrackingSceneLogic } from './errorTrackingSceneLogic'
import { ErrorTrackingSetupPrompt } from './ErrorTrackingSetupPrompt'
import { sparklineLabels, sparklineLabelsDay, sparklineLabelsMonth } from './utils'

export const scene: SceneExport = {
    component: ErrorTrackingScene,
    logic: errorTrackingSceneLogic,
}

export function ErrorTrackingScene(): JSX.Element {
    const { hasSentExceptionEvent, hasSentExceptionEventLoading } = useValues(errorTrackingLogic)
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
            occurrences: { align: 'center', render: CountColumn },
            sessions: { align: 'center', render: CountColumn },
            users: { align: 'center', render: CountColumn },
            volume: { align: 'right', renderTitle: VolumeColumnHeader, render: VolumeColumn },
            assignee: { align: 'center', render: AssigneeColumn },
        },
        showOpenEditorButton: false,
        insightProps: insightProps,
        emptyStateHeading: 'No issues found',
        emptyStateDetail: 'Try changing the date range, changing the filters or removing the assignee.',
    }

    return (
        <ErrorTrackingSetupPrompt>
            <BindLogic logic={errorTrackingDataNodeLogic} props={{ query, key: insightVizDataNodeKey(insightProps) }}>
                <Header />
                {hasSentExceptionEventLoading ? null : hasSentExceptionEvent ? (
                    <FeedbackNotice text="Error tracking is currently in beta. Thanks for taking part! We'd love to hear what you think." />
                ) : (
                    <IngestionStatusCheck />
                )}
                <ErrorTrackingFilters />
                <LemonDivider className="mt-2" />
                <ErrorTrackingListOptions />
                <Query query={query} context={context} />
            </BindLogic>
        </ErrorTrackingSetupPrompt>
    )
}

const VolumeColumn: QueryContextColumnComponent = (props) => {
    const { sparklineSelectedPeriod, customSparklineConfig } = useValues(errorTrackingLogic)
    const record = props.record as ErrorTrackingIssue

    if (!record.aggregations) {
        return null
    }

    const [data, labels] =
        sparklineSelectedPeriod === '24h'
            ? [record.aggregations.volumeDay, sparklineLabelsDay]
            : sparklineSelectedPeriod === '30d'
            ? [record.aggregations.volumeMonth, sparklineLabelsMonth]
            : customSparklineConfig
            ? [record.aggregations.customVolume, sparklineLabels(customSparklineConfig)]
            : [null, null]

    return data ? (
        <div className="flex justify-end">
            <Sparkline className="h-8" data={data} labels={labels} />
        </div>
    ) : null
}

const VolumeColumnHeader: QueryContextColumnTitleComponent = ({ columnName }) => {
    const { sparklineSelectedPeriod, sparklineOptions } = useValues(errorTrackingLogic)
    const { setSparklineSelectedPeriod: onChange } = useActions(errorTrackingLogic)

    return sparklineSelectedPeriod && sparklineOptions ? (
        <div className="flex justify-between items-center min-w-64">
            <div>{columnName}</div>
            <LemonSegmentedButton
                size="xsmall"
                value={sparklineSelectedPeriod}
                options={Object.values(sparklineOptions)}
                onChange={onChange}
            />
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
                className="pt-1"
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
                            <TZLabel time={record.first_seen} className="border-dotted border-b" delayMs={750} />
                            <span>|</span>
                            {record.last_seen ? (
                                <TZLabel time={record.last_seen} className="border-dotted border-b" delayMs={750} />
                            ) : (
                                <LemonSkeleton />
                            )}
                        </div>
                    </div>
                }
                className="flex-1 pr-12"
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

const CountColumn = ({ record, columnName }: { record: unknown; columnName: string }): JSX.Element => {
    const aggregations = (record as ErrorTrackingIssue).aggregations as ErrorTrackingIssueAggregations
    const count = aggregations[columnName as 'occurrences' | 'sessions' | 'users']

    return (
        <span className="text-lg font-medium">
            {columnName === 'sessions' && count === 0 ? (
                <Tooltip title="No $session_id was set for any event in this issue" delayMs={0}>
                    -
                </Tooltip>
            ) : (
                humanFriendlyLargeNumber(count)
            )}
        </span>
    )
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
                                posthog.captureException(new Error('Oh my!'))
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

const IngestionStatusCheck = (): JSX.Element | null => {
    return (
        <LemonBanner type="warning" className="my-4">
            <p>
                <strong>No Exception events have been detected!</strong>
            </p>
            <p>
                To use the Error tracking product, please{' '}
                <Link to="https://posthog.com/docs/error-tracking/installation">
                    enable exception capture within the PostHog SDK
                </Link>{' '}
                (otherwise it'll be a little empty!)
            </p>
        </LemonBanner>
    )
}

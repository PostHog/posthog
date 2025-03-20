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
import { TimeUnit } from 'chart.js'
import { BindLogic, useActions, useValues } from 'kea'
import { FeedbackNotice } from 'lib/components/FeedbackNotice'
import { PageHeader } from 'lib/components/PageHeader'
import { TZLabel } from 'lib/components/TZLabel'
import { FloatingContainerContext } from 'lib/hooks/useFloatingContainerContext'
import { humanFriendlyLargeNumber } from 'lib/utils'
import { posthog } from 'posthog-js'
import { useRef } from 'react'
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
import { StatusIndicator } from './issue/Indicator'
import { OccurrenceSparkline, useSparklineData } from './issue/OccurrenceSparkline'

export const scene: SceneExport = {
    component: ErrorTrackingScene,
    logic: errorTrackingSceneLogic,
}

export function ErrorTrackingScene(): JSX.Element {
    const { hasSentExceptionEvent, hasSentExceptionEventLoading } = useValues(errorTrackingLogic)
    const { query } = useValues(errorTrackingSceneLogic)
    const floatingContainerRef = useRef<HTMLDivElement>(null)
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
        refresh: 'blocking',
        showOpenEditorButton: false,
        insightProps: insightProps,
        emptyStateHeading: 'No issues found',
        emptyStateDetail: 'Try changing the date range, changing the filters or removing the assignee.',
    }

    return (
        <FloatingContainerContext.Provider value={floatingContainerRef}>
            <ErrorTrackingSetupPrompt>
                <BindLogic logic={errorTrackingDataNodeLogic} props={{ key: insightVizDataNodeKey(insightProps) }}>
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
        </FloatingContainerContext.Provider>
    )
}

const VolumeColumn: QueryContextColumnComponent = (props) => {
    const record = props.record as ErrorTrackingIssue
    const [values, unit, interval]: [number[], TimeUnit, number] = useSparklineData(record.aggregations)
    return values ? (
        <div className="flex justify-end">
            <OccurrenceSparkline className="h-8" unit={unit} interval={interval} displayXAxis={false} values={values} />
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
        <div className="flex items-start gap-x-2 group my-1">
            <LemonCheckbox
                className="h-[1.2rem]"
                checked={checked}
                onChange={(newValue) => {
                    setSelectedIssueIds(
                        newValue
                            ? [...new Set([...selectedIssueIds, record.id])]
                            : selectedIssueIds.filter((id) => id != record.id)
                    )
                }}
            />

            <div className="flex flex-col gap-[2px]">
                <Link
                    className="flex-1 pr-12"
                    to={urls.errorTrackingIssue(record.id)}
                    onClick={() => {
                        const issueLogic = errorTrackingIssueSceneLogic({ id: record.id })
                        issueLogic.mount()
                        issueLogic.actions.setIssue(record)
                    }}
                >
                    <div className="flex items-center font-semibold h-[1.2rem] text-[1.2em]">
                        {record.name || 'Unknown Type'}
                    </div>
                </Link>
                <div className="line-clamp-1 text-secondary">{record.description}</div>
                <div className="flex gap-1 items-center text-secondary">
                    <StatusIndicator size="xsmall" status={record.status} />
                    <span>|</span>
                    <TZLabel time={record.first_seen} className="border-dotted border-b text-xs" delayMs={750} />
                    <span>|</span>
                    {record.last_seen ? (
                        <TZLabel time={record.last_seen} className="border-dotted border-b text-xs" delayMs={750} />
                    ) : (
                        <LemonSkeleton />
                    )}
                </div>
            </div>
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

import { TZLabel } from '@posthog/apps-common'
import { IconGear } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonDivider, LemonMenuItems, LemonSegmentedButton } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { FeedbackNotice } from 'lib/components/FeedbackNotice'
import { PageHeader } from 'lib/components/PageHeader'
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
            sessions: { align: 'center', render: CountColumn },
            users: { align: 'center', render: CountColumn },
            volume: { renderTitle: CustomVolumeColumnHeader },
            assignee: { render: AssigneeColumn },
        },
        showOpenEditorButton: false,
        insightProps: insightProps,
    }

    return (
        <AlphaAccessScenePrompt>
            <BindLogic logic={errorTrackingDataNodeLogic} props={{ query, key: insightVizDataNodeKey(insightProps) }}>
                <Header />
                <FeedbackNotice text="Error tracking is in closed alpha. Thanks for taking part! We'd love to hear what you think." />
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

const CustomVolumeColumnHeader: QueryContextColumnTitleComponent = ({ columnName }) => {
    const { sparklineSelectedPeriod, sparklineOptions: options } = useValues(errorTrackingLogic)
    const { setSparklineSelectedPeriod } = useActions(errorTrackingLogic)

    if (!sparklineSelectedPeriod) {
        return null
    }

    return (
        <div className="flex items-center justify-between min-w-64">
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
                            <TZLabel time={record.first_seen} className="border-b border-dotted" />
                            <span>|</span>
                            <TZLabel time={record.last_seen} className="border-b border-dotted" />
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

const CountColumn: QueryContextColumnComponent = ({ value }) => {
    return <>{humanFriendlyLargeNumber(value as number)}</>
}

const AssigneeColumn: QueryContextColumnComponent = (props) => {
    const { assignIssue } = useActions(errorTrackingDataNodeLogic)

    const record = props.record as ErrorTrackingIssue

    return (
        <div className="flex justify-center">
            <AssigneeSelect assignee={record.assignee} onChange={(assigneeId) => assignIssue(record.id, assigneeId)} />
        </div>
    )
}

const Header = (): JSX.Element => {
    const { user } = useValues(userLogic)

    const items: LemonMenuItems = [{ label: 'Manage symbol sets', to: urls.errorTrackingSymbolSets() }]

    if (user?.is_staff) {
        items.push({
            label: 'Send an exception',
            onClick: () => {
                throw Error('Oh my!')
            },
        })
    }

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
                    <LemonButton to={urls.errorTrackingAlerts()} type="secondary" icon={<IconGear />}>
                        Configure alerts
                    </LemonButton>
                    <LemonButton to={urls.errorTrackingConfiguration()} type="secondary" icon={<IconGear />}>
                        Configure
                    </LemonButton>
                </>
            }
        />
    )
}

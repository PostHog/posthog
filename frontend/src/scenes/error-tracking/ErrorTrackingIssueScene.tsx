import './ErrorTracking.scss'

import { IconCollapse, IconExpand } from '@posthog/icons'
import { LemonTabs } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import PanelLayout, { SettingsToggle } from 'lib/components/PanelLayout/PanelLayout'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { resizerLogic, ResizerLogicProps } from 'lib/components/Resizer/resizerLogic'
import { useEffect, useRef, useState } from 'react'
import { EventDetails } from 'scenes/activity/explore/EventDetails'
import { SceneExport } from 'scenes/sceneTypes'
import { SettingsBar } from 'scenes/session-recordings/components/PanelSettings'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

import { AssigneeSelect } from './AssigneeSelect'
import { ContextDisplay } from './components/ContextDisplay'
import { RecordingPlayer } from './components/RecordingPlayer'
import { StacktraceDisplay } from './components/StacktraceDisplay'
import { DateRangeFilter, FilterGroup, InternalAccountsFilter } from './ErrorTrackingFilters'
import { errorTrackingIssueSceneLogic } from './errorTrackingIssueSceneLogic'
import { ErrorTrackingSetupPrompt } from './ErrorTrackingSetupPrompt'
import { GenericSelect } from './issue/GenericSelect'
import { IssueStatus, StatusIndicator } from './issue/Indicator'
import { Metadata } from './issue/Metadata'
import { EventsTab } from './issue/tabs/EventsTab'

export const scene: SceneExport = {
    component: ErrorTrackingIssueScene,
    logic: errorTrackingIssueSceneLogic,
    paramsToProps: ({
        params: { id },
        searchParams: { fingerprint },
    }): (typeof errorTrackingIssueSceneLogic)['props'] => ({ id, fingerprint }),
}

export const STATUS_LABEL: Record<ErrorTrackingIssue['status'], string> = {
    active: 'Active',
    archived: 'Archived',
    resolved: 'Resolved',
    pending_release: 'Pending release',
    suppressed: 'Suppressed',
}

export function ErrorTrackingIssueScene(): JSX.Element {
    const { issue, issueLoading, activeException } = useValues(errorTrackingIssueSceneLogic)
    const { loadIssue, updateStatus, updateAssignee } = useActions(errorTrackingIssueSceneLogic)

    const ref = useRef<HTMLDivElement>(null)

    const resizerLogicProps: ResizerLogicProps = {
        containerRef: ref,
        logicKey: 'error-tracking-issue',
        persistent: true,
        placement: 'left',
    }

    const { desiredSize } = useValues(resizerLogic(resizerLogicProps))

    useEffect(() => {
        loadIssue()
    }, [loadIssue])

    return (
        <ErrorTrackingSetupPrompt>
            <PageHeader
                buttons={
                    <div className="flex gap-x-2">
                        {!issueLoading && issue?.status == 'active' && (
                            <AssigneeSelect
                                assignee={issue?.assignee}
                                onChange={updateAssignee}
                                type="secondary"
                                showName
                            />
                        )}
                        {!issueLoading && (
                            <GenericSelect
                                size="small"
                                current={issue?.status}
                                values={['active', 'resolved', 'suppressed']}
                                placeholder="Mark as"
                                renderValue={(value) => (
                                    <StatusIndicator status={value as IssueStatus} size="small" withTooltip={true} />
                                )}
                                onChange={updateStatus}
                            />
                        )}
                    </div>
                }
            />
            <div className="ErrorTrackingIssue flex">
                <div className="flex flex-col flex-1 overflow-x-auto">
                    {activeException ? (
                        <div className="flex-1">
                            <EventDetails event={activeException} />
                        </div>
                    ) : (
                        <ExceptionContent />
                    )}
                    <WorkspaceSettings />
                </div>
                <div
                    className="flex relative bg-surface-primary min-w-[420px]"
                    ref={ref}
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ width: desiredSize ?? undefined }}
                >
                    <Resizer {...resizerLogicProps} />
                    <div className="ErrorTrackingIssue__sidebar overflow-y-auto space-y-4 pt-2 w-full">
                        <Filters />
                        <Metadata />
                        <LemonTabs
                            size="small"
                            tabs={[
                                { key: 'events', label: <div className="px-2">Events</div>, content: <EventsTab /> },
                            ]}
                            activeKey="events"
                        />
                    </div>
                </div>
            </div>
        </ErrorTrackingSetupPrompt>
    )
}

const Filters = (): JSX.Element => {
    return (
        <div className="px-2 flex items-center flex-col gap-1">
            <FilterGroup />
            <div className="flex flex-wrap-reverse justify-between w-full gap-1">
                <DateRangeFilter />
                <InternalAccountsFilter />
            </div>
        </div>
    )
}

const ExceptionContent = (): JSX.Element => {
    const [activeKey, setActiveKey] = useState<'overview' | 'recording' | 'properties'>('overview')

    return (
        <div className="flex-1 overflow-y-auto p-2">
            <PanelLayout column>
                <PanelLayout.Panel primary={false}>
                    <StacktraceDisplay />
                </PanelLayout.Panel>
            </PanelLayout>
            <LemonTabs
                activeKey={activeKey}
                tabs={[
                    {
                        key: 'overview',
                        label: 'Overview',
                        content: <ContextDisplay />,
                    },
                    {
                        key: 'recording',
                        label: 'Recording',
                        content: <RecordingPlayer />,
                    },
                ]}
                onChange={setActiveKey}
            />
        </div>
    )
}

const WorkspaceSettings = (): JSX.Element => {
    const { showAllFrames, activeException } = useValues(errorTrackingIssueSceneLogic)
    const { setShowAllFrames, setActiveException } = useActions(errorTrackingIssueSceneLogic)

    return (
        <SettingsBar border="top" className="bg-surface-primary justify-between">
            <SettingsToggle
                active
                tooltip={!activeException ? 'Select an event to view' : undefined}
                label={activeException ? 'View latest exception' : 'Latest exception'}
                onClick={() => activeException && setActiveException(null)}
            />
            <SettingsToggle
                label={showAllFrames ? 'Hide extra frames' : 'Show all frames'}
                active={false}
                icon={showAllFrames ? <IconCollapse /> : <IconExpand />}
                size="xsmall"
                onClick={() => setShowAllFrames(!showAllFrames)}
            />
        </SettingsBar>
    )
}

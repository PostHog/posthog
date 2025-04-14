import './ErrorTracking.scss'

import { LemonDivider } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import PanelLayout, { PanelSettings, SettingsToggle } from 'lib/components/PanelLayout/PanelLayout'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { resizerLogic, ResizerLogicProps } from 'lib/components/Resizer/resizerLogic'
import { useEffect, useRef } from 'react'
import { SceneExport } from 'scenes/sceneTypes'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

import { AssigneeSelect } from './AssigneeSelect'
import { ContextDisplay } from './components/ContextDisplay'
import { IssueCard } from './components/IssueCard'
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
    const { issue, issueLoading, showAllFrames } = useValues(errorTrackingIssueSceneLogic)
    const { loadIssue, updateStatus, updateAssignee, setShowAllFrames } = useActions(errorTrackingIssueSceneLogic)

    const ref = useRef<HTMLDivElement>(null)

    const resizerLogicProps: ResizerLogicProps = {
        logicKey: 'error-tracking-issue',
        placement: 'right',
        containerRef: ref,
        persistent: true,
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
                <div
                    className="ErrorTrackingIssue__left-column relative bg-surface-primary overflow-y-auto"
                    ref={ref}
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{
                        width: desiredSize || 100,
                    }}
                >
                    <div className="p-2 space-y-2">
                        <IssueCard />
                        <LemonDivider />
                        <div className="flex items-center flex-col gap-1">
                            <FilterGroup />
                            <div className="h-full flex flex-wrap justify-center w-full gap-2">
                                <DateRangeFilter />
                                <InternalAccountsFilter />
                            </div>
                        </div>
                        <Metadata />
                    </div>
                    <div>
                        <EventsTab />
                    </div>
                    <Resizer {...resizerLogicProps} offset={1} />
                </div>
                <div className="flex-1 overflow-y-auto p-2">
                    <div className="space-y-2">
                        <PanelLayout.Panel primary={false}>
                            <PanelSettings title="Details" border="bottom" />
                            <ContextDisplay />
                        </PanelLayout.Panel>
                        <PanelLayout.Panel primary={false}>
                            <PanelSettings title="Stack trace" border="bottom">
                                <SettingsToggle
                                    label="Show all frames"
                                    active={showAllFrames}
                                    size="xsmall"
                                    onClick={() => setShowAllFrames(!showAllFrames)}
                                />
                            </PanelSettings>
                            <StacktraceDisplay className="p-2" />
                        </PanelLayout.Panel>
                        <PanelLayout.Panel primary={false}>
                            <PanelSettings title="Replay" border="bottom" />
                            <RecordingPlayer />
                        </PanelLayout.Panel>
                    </div>
                </div>
            </div>
        </ErrorTrackingSetupPrompt>
    )
}

import './ErrorTracking.scss'

import { IconCollapse, IconExpand } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import PanelLayout, { PanelSettings, SettingsToggle } from 'lib/components/PanelLayout/PanelLayout'
import { useEffect } from 'react'
import { SceneExport } from 'scenes/sceneTypes'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

import { AssigneeSelect } from './AssigneeSelect'
import { ContextDisplay } from './components/ContextDisplay'
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
    const { issue, issueLoading } = useValues(errorTrackingIssueSceneLogic)
    const { loadIssue, updateStatus, updateAssignee } = useActions(errorTrackingIssueSceneLogic)

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
            <div className="ErrorTrackingIssue flex flex-col gap-3">
                <div className="p-1 gap-1 bg-surface-primary border-b">
                    <div className="flex items-center gap-1">
                        <DateRangeFilter />
                        <FilterGroup />
                        <InternalAccountsFilter />
                    </div>
                    <Metadata />
                </div>
                <div className="flex flex-1 gap-3 px-2 pb-2">
                    <PanelLayout.Panel primary={false} className="w-1/3">
                        <EventsTab />
                    </PanelLayout.Panel>
                    <ExceptionContent />
                </div>
            </div>
        </ErrorTrackingSetupPrompt>
    )
}

const ExceptionContent = (): JSX.Element => {
    const { showAllFrames } = useValues(errorTrackingIssueSceneLogic)
    const { setShowAllFrames } = useActions(errorTrackingIssueSceneLogic)

    return (
        <PanelLayout column className="flex-1 overflow-y-auto">
            <PanelLayout.Panel primary={false}>
                <ContextDisplay />
            </PanelLayout.Panel>
            <PanelLayout.Panel primary={false}>
                <PanelSettings title="Stack" border="bottom">
                    <SettingsToggle
                        label="Show all frames"
                        active={true}
                        icon={showAllFrames ? <IconCollapse /> : <IconExpand />}
                        size="xsmall"
                        onClick={() => setShowAllFrames(!showAllFrames)}
                    />
                </PanelSettings>
                <StacktraceDisplay />
            </PanelLayout.Panel>
        </PanelLayout>
    )
}

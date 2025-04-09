import './ErrorTracking.scss'

import { LemonTabs } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { useEffect, useState } from 'react'
import { SceneExport } from 'scenes/sceneTypes'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

import { AssigneeSelect } from './AssigneeSelect'
import { ErrorTrackingFilters } from './ErrorTrackingFilters'
import { errorTrackingIssueSceneLogic } from './errorTrackingIssueSceneLogic'
import { ErrorTrackingSetupPrompt } from './ErrorTrackingSetupPrompt'
import { GenericSelect } from './issue/GenericSelect'
import { IssueStatus, StatusIndicator } from './issue/Indicator'
import { Metadata } from './issue/Metadata'
import { EventsTab } from './issue/tabs/EventsTab'
import { DetailsWidget } from './issue/widgets/DetailsWidget'
import { StacktraceWidget } from './issue/widgets/StacktraceWidget'

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
    const [activeTab, setActiveTab] = useState('stacktrace')

    useEffect(() => {
        loadIssue()
    }, [loadIssue])

    return (
        <ErrorTrackingSetupPrompt>
            <>
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
                                        <StatusIndicator
                                            status={value as IssueStatus}
                                            size="small"
                                            withTooltip={true}
                                        />
                                    )}
                                    onChange={updateStatus}
                                />
                            )}
                        </div>
                    }
                />
                <div className="ErrorTrackingIssue">
                    <Metadata />
                    <LemonTabs
                        activeKey={activeTab}
                        onChange={(key) => setActiveTab(key)}
                        tabs={[
                            {
                                key: 'stacktrace',
                                label: 'Overview',
                                content: (
                                    <div className="space-y-2">
                                        <DetailsWidget />
                                        <StacktraceWidget />
                                    </div>
                                ),
                            },
                            {
                                key: 'events',
                                label: 'Events',
                                content: (
                                    <div className="space-y-2">
                                        <ErrorTrackingFilters />
                                        <div className="border-1 overflow-hidden border-accent border-primary rounded bg-surface-primary relative">
                                            <EventsTab />
                                        </div>
                                    </div>
                                ),
                            },
                        ]}
                    />
                </div>
            </>
        </ErrorTrackingSetupPrompt>
    )
}

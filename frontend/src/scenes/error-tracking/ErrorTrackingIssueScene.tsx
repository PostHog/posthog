import './ErrorTracking.scss'

import { LemonCard } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { useEffect } from 'react'
import { SceneExport } from 'scenes/sceneTypes'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

import { AssigneeSelect } from './AssigneeSelect'
import { IssueCard } from './components/IssueCard'
import {
    DateRangeFilter,
    ErrorTrackingFilters,
    FilterGroup,
    InternalAccountsFilter,
    UniversalSearch,
} from './ErrorTrackingFilters'
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
            <div className="ErrorTrackingIssue space-y-2">
                <IssueCard />
                <Metadata />
                <ErrorTrackingFilters>
                    <DateRangeFilter />
                    <FilterGroup />
                    <UniversalSearch />
                    <InternalAccountsFilter />
                </ErrorTrackingFilters>
                <LemonCard className="p-0 overflow-hidden" hoverEffect={false}>
                    <EventsTab />
                </LemonCard>
            </div>
        </ErrorTrackingSetupPrompt>
    )
}

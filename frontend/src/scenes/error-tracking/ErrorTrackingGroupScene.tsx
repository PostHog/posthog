import './ErrorTracking.scss'

import { LemonButton, LemonDivider } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { useEffect } from 'react'
import { SceneExport } from 'scenes/sceneTypes'

import { ErrorTrackingIssue } from '~/queries/schema'

import { AssigneeSelect } from './AssigneeSelect'
import ErrorTrackingFilters from './ErrorTrackingFilters'
import { errorTrackingGroupSceneLogic } from './errorTrackingGroupSceneLogic'
import { OverviewTab } from './groups/OverviewTab'
import { SymbolSetUploadModal } from './SymbolSetUploadModal'

export const scene: SceneExport = {
    component: ErrorTrackingGroupScene,
    logic: errorTrackingGroupSceneLogic,
    paramsToProps: ({ params: { id } }): (typeof errorTrackingGroupSceneLogic)['props'] => ({ id }),
}

const STATUS_LABEL: Record<ErrorTrackingIssue['status'], string> = {
    active: 'Active',
    archived: 'Archived',
    resolved: 'Resolved',
    pending_release: 'Pending release',
}

export function ErrorTrackingGroupScene(): JSX.Element {
    const { issue, issueLoading, hasGroupActions } = useValues(errorTrackingGroupSceneLogic)
    const { updateIssue, loadIssue } = useActions(errorTrackingGroupSceneLogic)

    useEffect(() => {
        // don't like doing this but scene logics do not unmount after being loaded
        // so this refreshes the group on each page visit in case any changes occurred
        if (!issueLoading) {
            loadIssue()
        }
    }, [])

    return (
        <>
            <PageHeader
                buttons={
                    issue && hasGroupActions ? (
                        issue.status === 'active' ? (
                            <div className="flex divide-x gap-x-2">
                                <AssigneeSelect
                                    assignee={issue.assignee}
                                    onChange={(assignee) => updateIssue({ assignee })}
                                    type="secondary"
                                    showName
                                />
                                <div className="flex pl-2 gap-x-2">
                                    <LemonButton type="secondary" onClick={() => updateIssue({ status: 'archived' })}>
                                        Archive
                                    </LemonButton>
                                    <LemonButton type="primary" onClick={() => updateIssue({ status: 'resolved' })}>
                                        Resolve
                                    </LemonButton>
                                </div>
                            </div>
                        ) : (
                            <LemonButton
                                type="secondary"
                                className="upcasefirst-letter:uppercase"
                                onClick={() => updateIssue({ status: 'active' })}
                                tooltip="Mark as active"
                            >
                                {STATUS_LABEL[issue.status]}
                            </LemonButton>
                        )
                    ) : (
                        false
                    )
                }
            />
            <ErrorTrackingFilters.FilterGroup />
            <LemonDivider className="mt-2" />
            <ErrorTrackingFilters.Options isGroup />
            <OverviewTab />
            <SymbolSetUploadModal />
        </>
    )
}

import './ErrorTracking.scss'

import { LemonButton, LemonTabs, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { useEffect } from 'react'
import { SceneExport } from 'scenes/sceneTypes'

import { ErrorTrackingIssue } from '~/queries/schema'

import { AlphaAccessScenePrompt } from './AlphaAccessScenePrompt'
import { AssigneeSelect } from './AssigneeSelect'
import { errorTrackingIssueSceneLogic, IssueTab } from './errorTrackingIssueSceneLogic'
import { EventsTab } from './issue/tabs/EventsTab'
import { OverviewTab } from './issue/tabs/OverviewTab'

export const scene: SceneExport = {
    component: ErrorTrackingIssueScene,
    logic: errorTrackingIssueSceneLogic,
    paramsToProps: ({ params: { id } }): (typeof errorTrackingIssueSceneLogic)['props'] => ({ id }),
}

const STATUS_LABEL: Record<ErrorTrackingIssue['status'], string> = {
    active: 'Active',
    archived: 'Archived',
    resolved: 'Resolved',
    pending_release: 'Pending release',
}

export function ErrorTrackingIssueScene(): JSX.Element {
    const { issue, issueLoading, hasGroupActions, tab } = useValues(errorTrackingIssueSceneLogic)
    const { updateIssue, loadIssue, setTab } = useActions(errorTrackingIssueSceneLogic)

    useEffect(() => {
        // don't like doing this but scene logics do not unmount after being loaded
        // so this refreshes the group on each page visit in case any changes occurred
        if (!issueLoading) {
            loadIssue()
        }
    }, [])

    return (
        <AlphaAccessScenePrompt>
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
                                        <LemonButton
                                            type="secondary"
                                            onClick={() => updateIssue({ status: 'archived' })}
                                        >
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
                {issue ? (
                    <LemonTabs
                        activeKey={tab}
                        tabs={[
                            {
                                key: IssueTab.Overview,
                                label: 'Overview',
                                content: <OverviewTab />,
                            },

                            {
                                key: IssueTab.Events,
                                label: 'Events',
                                content: <EventsTab />,
                            },
                        ]}
                        onChange={setTab}
                    />
                ) : (
                    <Spinner />
                )}
            </>
        </AlphaAccessScenePrompt>
    )
}

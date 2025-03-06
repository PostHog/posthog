import './ErrorTracking.scss'

import { LemonButton, LemonDivider, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import PanelLayout from 'lib/components/PanelLayout/PanelLayout'
import { useEffect } from 'react'
import { SceneExport } from 'scenes/sceneTypes'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

import { AssigneeSelect } from './AssigneeSelect'
import { errorTrackingIssueSceneLogic } from './errorTrackingIssueSceneLogic'
import { ErrorTrackingSetupPrompt } from './ErrorTrackingSetupPrompt'
import { Events } from './issue/Events'
import { Metadata } from './issue/Metadata'
import { SparklinePanel } from './issue/Sparkline'

export const scene: SceneExport = {
    component: ErrorTrackingIssueScene,
    logic: errorTrackingIssueSceneLogic,
    paramsToProps: ({
        params: { id },
        searchParams: { fingerprint },
    }): (typeof errorTrackingIssueSceneLogic)['props'] => ({ id, fingerprint }),
}

const STATUS_LABEL: Record<ErrorTrackingIssue['status'], string> = {
    active: 'Active',
    archived: 'Archived',
    resolved: 'Resolved',
    pending_release: 'Pending release',
}

export function ErrorTrackingIssueScene(): JSX.Element {
    const { issue } = useValues(errorTrackingIssueSceneLogic)
    const { updateIssue, initIssue, assignIssue } = useActions(errorTrackingIssueSceneLogic)

    useEffect(() => {
        initIssue()
    }, [])

    return (
        <ErrorTrackingSetupPrompt>
            <>
                <PageHeader
                    buttons={
                        issue ? (
                            issue.status === 'active' ? (
                                <div className="flex divide-x gap-x-2">
                                    <AssigneeSelect
                                        assignee={issue.assignee}
                                        onChange={assignIssue}
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
                    <div className="ErrorTrackingIssue">
                        <Metadata />
                        <LemonDivider className="my-4" />
                        <PanelLayout>
                            <PanelLayout.Container column primary>
                                <SparklinePanel />
                                <PanelLayout.Panel primary>
                                    <Events />
                                </PanelLayout.Panel>
                            </PanelLayout.Container>
                        </PanelLayout>
                    </div>
                ) : (
                    <Spinner />
                )}
            </>
        </ErrorTrackingSetupPrompt>
    )
}

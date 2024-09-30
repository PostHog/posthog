import './ErrorTracking.scss'

import { LemonButton, LemonDivider } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { base64Decode } from 'lib/utils'
import { useEffect } from 'react'
import { SceneExport } from 'scenes/sceneTypes'

import { ErrorTrackingGroup } from '~/queries/schema'

import { AssigneeSelect } from './AssigneeSelect'
import ErrorTrackingFilters from './ErrorTrackingFilters'
import { errorTrackingGroupSceneLogic } from './errorTrackingGroupSceneLogic'
import { OverviewTab } from './groups/OverviewTab'

export const scene: SceneExport = {
    component: ErrorTrackingGroupScene,
    logic: errorTrackingGroupSceneLogic,
    paramsToProps: ({ params: { fingerprint } }): (typeof errorTrackingGroupSceneLogic)['props'] => ({
        fingerprint: JSON.parse(base64Decode(decodeURIComponent(fingerprint))),
    }),
}

const STATUS_LABEL: Record<ErrorTrackingGroup['status'], string> = {
    active: 'Active',
    archived: 'Archived',
    resolved: 'Resolved',
    pending_release: 'Pending release',
}

export function ErrorTrackingGroupScene(): JSX.Element {
    const { group, groupLoading } = useValues(errorTrackingGroupSceneLogic)
    const { updateGroup, loadGroup } = useActions(errorTrackingGroupSceneLogic)

    useEffect(() => {
        // don't like doing this but scene logics do not unmount after being loaded
        // so this refreshes the group on each page visit in case any changes occurred
        if (!groupLoading) {
            loadGroup()
        }
    }, [])

    return (
        <>
            <PageHeader
                buttons={
                    group ? (
                        group.status === 'active' ? (
                            <div className="flex divide-x gap-x-2">
                                <AssigneeSelect
                                    assignee={group.assignee}
                                    onChange={(assignee) => updateGroup({ assignee })}
                                    type="secondary"
                                    showName
                                />
                                <div className="flex pl-2 gap-x-2">
                                    <LemonButton type="secondary" onClick={() => updateGroup({ status: 'archived' })}>
                                        Archive
                                    </LemonButton>
                                    <LemonButton type="primary" onClick={() => updateGroup({ status: 'resolved' })}>
                                        Resolve
                                    </LemonButton>
                                </div>
                            </div>
                        ) : (
                            <LemonButton
                                type="secondary"
                                className="upcasefirst-letter:uppercase"
                                onClick={() => updateGroup({ status: 'active' })}
                                tooltip="Mark as active"
                            >
                                {STATUS_LABEL[group.status]}
                            </LemonButton>
                        )
                    ) : (
                        false
                    )
                }
            />
            <ErrorTrackingFilters.FilterGroup />
            <LemonDivider className="mt-2" />
            <ErrorTrackingFilters.Options showOrder={false} />
            <div className="pt-2">
                <OverviewTab />
            </div>
        </>
    )
}

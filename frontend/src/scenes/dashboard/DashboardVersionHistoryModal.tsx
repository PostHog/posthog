import { useActions, useValues } from 'kea'

import { LemonDialog } from '@posthog/lemon-ui'

import { humanize } from 'lib/components/ActivityLog/humanizeActivity'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { dashboardActivityDescriber } from 'scenes/dashboard/dashboardActivityDescriber'

import { ActivityScope, DashboardVersionListItem } from '~/types'

import { dashboardVersionHistoryLogic } from './dashboardVersionHistoryLogic'

interface DashboardVersionHistoryModalProps {
    dashboardId: number
    canEdit: boolean
}

export function DashboardVersionHistoryModal({
    dashboardId,
    canEdit,
}: DashboardVersionHistoryModalProps): JSX.Element {
    const logic = dashboardVersionHistoryLogic({ dashboardId })
    const { isOpen, versions, versionsLoading, revertingVersionId } = useValues(logic)
    const { closeVersionHistory, revertToVersion } = useActions(logic)

    return (
        <LemonModal
            title="Version history"
            description="Every change to this dashboard is recorded. Restore an earlier version to undo recent edits."
            isOpen={isOpen}
            onClose={closeVersionHistory}
            width={720}
        >
            {versionsLoading && versions.length === 0 ? (
                <div className="flex flex-col gap-2 py-4">
                    <LemonSkeleton className="h-12" />
                    <LemonSkeleton className="h-12" />
                    <LemonSkeleton className="h-12" />
                </div>
            ) : versions.length === 0 ? (
                <div className="py-8 text-center text-secondary">
                    No version history yet. As edits are made, they will appear here.
                </div>
            ) : (
                <ul className="flex flex-col gap-0 list-none p-0 m-0">
                    {versions.map((version, index) => (
                        <DashboardVersionRow
                            key={version.version_id}
                            version={version}
                            isCurrent={index === 0}
                            canEdit={canEdit}
                            isReverting={revertingVersionId === version.version_id}
                            onRevert={() => {
                                LemonDialog.open({
                                    title: 'Revert dashboard to this version?',
                                    description:
                                        'This will overwrite the dashboard configuration (name, description, filters, variables, and settings) with the values from this version. Tiles and tags are not affected. This action itself is recorded in the version history.',
                                    primaryButton: {
                                        children: 'Revert',
                                        status: 'danger',
                                        onClick: () => revertToVersion(version.version_id),
                                    },
                                    secondaryButton: { children: 'Cancel' },
                                })
                            }}
                        />
                    ))}
                </ul>
            )}
        </LemonModal>
    )
}

interface DashboardVersionRowProps {
    version: DashboardVersionListItem
    isCurrent: boolean
    canEdit: boolean
    isReverting: boolean
    onRevert: () => void
}

function DashboardVersionRow({
    version,
    isCurrent,
    canEdit,
    isReverting,
    onRevert,
}: DashboardVersionRowProps): JSX.Element {
    const actorLabel = renderActor(version)
    const summary = renderSummary(version)

    return (
        <li className="flex flex-col py-3">
            <div className="flex items-start gap-3">
                <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                        {actorLabel}
                        <TZLabel time={version.created_at} />
                        {isCurrent && (
                            <span className="text-xs px-2 py-0.5 rounded bg-accent-highlight-secondary text-accent">
                                Current
                            </span>
                        )}
                        {version.was_impersonated && (
                            <span className="text-xs px-2 py-0.5 rounded bg-warning-highlight text-warning">
                                Impersonated
                            </span>
                        )}
                        {version.is_system && (
                            <span className="text-xs px-2 py-0.5 rounded bg-surface-secondary text-secondary">
                                System
                            </span>
                        )}
                    </div>
                    <div className="text-sm text-secondary mt-1 break-words">{summary}</div>
                </div>
                {!isCurrent && canEdit && (
                    <LemonButton
                        size="small"
                        type="secondary"
                        onClick={onRevert}
                        loading={isReverting}
                        data-attr="dashboard-revert-to-version"
                    >
                        Revert
                    </LemonButton>
                )}
                {isReverting && isCurrent && <Spinner />}
            </div>
            <LemonDivider className="my-0 mt-3" />
        </li>
    )
}

function renderActor(version: DashboardVersionListItem): JSX.Element {
    const client = version.client
    if (version.is_system && !version.user) {
        return (
            <span className="flex items-center gap-2 font-medium">
                System
                {client && <span className="text-xs text-secondary">via {client}</span>}
            </span>
        )
    }
    if (!version.user) {
        return <span className="font-medium">Unknown</span>
    }
    return (
        <span className="flex items-center gap-2 font-medium">
            <ProfilePicture user={version.user} size="md" />
            <span className="truncate">
                {version.user.first_name || version.user.email}
                {version.user.last_name ? ` ${version.user.last_name}` : ''}
            </span>
            {client && <span className="text-xs text-secondary">via {client}</span>}
        </span>
    )
}

function renderSummary(version: DashboardVersionListItem): JSX.Element {
    if (version.activity === 'created') {
        return <span>Created the dashboard.</span>
    }
    if (version.activity === 'deleted') {
        return <span>Deleted the dashboard.</span>
    }
    if (version.activity === 'restored') {
        return <span>Restored the dashboard.</span>
    }

    // For updates, reuse the existing humanizer to produce the same wording as the activity feed.
    const fakeLogItem = {
        id: version.version_id,
        scope: ActivityScope.DASHBOARD,
        activity: version.activity,
        created_at: version.created_at,
        user: version.user
            ? {
                  first_name: version.user.first_name,
                  last_name: version.user.last_name,
                  email: version.user.email,
              }
            : undefined,
        is_system: version.is_system,
        was_impersonated: version.was_impersonated,
        detail: {
            merge: null,
            trigger: null,
            changes: version.detail?.changes ?? null,
            name: (version.detail?.name as string | null | undefined) ?? null,
        },
    }
    const [humanized] = humanize([fakeLogItem as any], () => dashboardActivityDescriber)
    return <span>{humanized?.description ?? 'Updated the dashboard.'}</span>
}

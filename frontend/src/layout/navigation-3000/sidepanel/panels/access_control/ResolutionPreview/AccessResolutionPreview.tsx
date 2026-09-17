import { useActions, useValues } from 'kea'

import { IconExternal, IconGear } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCollapse,
    LemonTable,
    LemonTableColumns,
    LemonTag,
    Link,
    Spinner,
} from '@posthog/lemon-ui'

import { supportLogic } from 'lib/components/Support/supportLogic'
import { urls } from 'scenes/urls'

import { objectRuleUrl } from '~/layout/navigation-3000/sidepanel/panels/access_control/ResourceAccessControlsV2/accessDetailLogic'
import { humanizeAccessControlLevel } from '~/layout/navigation-3000/sidepanel/panels/access_control/ResourceAccessControlsV2/helpers'
import { APIScopeObject, AccessControlLevel } from '~/types'

import { describeResolutionChange } from './describeResolutionChange'
import { ResolutionChange, resolutionPreviewLogic } from './resolutionPreviewLogic'

function WhyExplainer(): JSX.Element {
    return (
        <LemonCollapse
            panels={[
                {
                    key: 'why',
                    header: 'Why are we changing this?',
                    content: (
                        <div className="flex flex-col gap-2 max-w-200">
                            <p className="mb-0">
                                We want access control to support both allowlist and denylist setups. For example:
                            </p>
                            <p className="mb-0">
                                <strong>Allowlist:</strong> your project is private (No access by default), and you
                                grant specific members or roles access above that. This already works.
                            </p>
                            <p className="mb-0">
                                <strong>Denylist:</strong> your project is open to the organization (Member by default),
                                and you want to exclude one role. Today the highest rule applies, so the only way is to
                                set the default to No access and grant access back to everyone else. Once the most
                                specific rule applies, you set No access for that one role and keep the open default.
                            </p>
                        </div>
                    ),
                },
            ]}
        />
    )
}

function urlForChangeObject(change: ResolutionChange): string | null {
    if (change.object_id === null) {
        return null
    }
    // Same link rules as the object rules table on the access control settings page
    return objectRuleUrl({
        resource: change.resource as APIScopeObject,
        resource_id: change.object_id,
        name: change.object_name ?? change.object_id,
        short_id: change.object_short_id,
        access_level: change.proposed.access_level as AccessControlLevel,
    })
}

function SubjectCell({ change }: { change: ResolutionChange }): JSX.Element {
    return (
        <div className="flex items-center gap-2 whitespace-nowrap">
            <span className="font-semibold max-w-60 truncate" title={change.subject.name}>
                {change.subject.name}
            </span>
            <LemonTag size="small">{change.subject.type}</LemonTag>
        </div>
    )
}

function LevelChangeCell({ change }: { change: ResolutionChange }): JSX.Element {
    return (
        <div className="flex items-center gap-2 whitespace-nowrap">
            <LemonTag>{humanizeAccessControlLevel(change.current.access_level as AccessControlLevel)}</LemonTag>
            <span aria-hidden="true">→</span>
            <LemonTag type={change.direction === 'gains' ? 'warning' : 'danger'}>
                {humanizeAccessControlLevel(change.proposed.access_level as AccessControlLevel)}
            </LemonTag>
        </div>
    )
}

const sharedColumns: LemonTableColumns<ResolutionChange> = [
    {
        title: 'Applies to',
        key: 'subject',
        width: 0,
        render: (_, change) => <SubjectCell change={change} />,
    },
    {
        title: 'Access',
        key: 'change',
        render: (_, change) => <LevelChangeCell change={change} />,
    },
    {
        title: 'Why',
        key: 'why',
        render: (_, change) => <span className="text-muted">{describeResolutionChange(change)}</span>,
    },
]

export function AccessResolutionPreview(): JSX.Element {
    const { preview, previewLoading, previewForbidden } = useValues(resolutionPreviewLogic)
    const { loadPreview } = useActions(resolutionPreviewLogic)
    const { openSupportForm } = useActions(supportLogic)

    if (previewLoading) {
        return <Spinner className="text-lg" />
    }
    if (previewForbidden) {
        return (
            <LemonBanner type="info">
                Only administrators can view the resolution preview. Ask an organization admin to review the changes.
            </LemonBanner>
        )
    }
    if (!preview) {
        return (
            <LemonBanner
                type="error"
                action={{ children: 'Try again', onClick: () => loadPreview(), 'data-attr': 'access-resolution-retry' }}
            >
                Couldn't load the resolution preview. Try again, and if it keeps happening contact support.
            </LemonBanner>
        )
    }
    if (preview.summary.total === 0) {
        return (
            <div className="flex flex-col gap-4">
                <WhyExplainer />
                <LemonBanner type="success">
                    No access rules resolve differently in the projects you administer. Nothing changes when the new
                    resolution takes effect.
                </LemonBanner>
            </div>
        )
    }

    const projects = Array.from(
        new Map(preview.changes.map((change) => [change.project_id, change.project_name])).entries()
    ).sort((a, b) => a[1].localeCompare(b[1]))

    const resourceColumns: LemonTableColumns<ResolutionChange> = [
        {
            title: 'Setting',
            key: 'resource',
            width: 0,
            render: (_, change) => (
                <span className="font-semibold capitalize whitespace-nowrap">{change.resource.replace(/_/g, ' ')}</span>
            ),
        },
        ...sharedColumns,
        {
            key: 'actions',
            width: 0,
            render: () => (
                <LemonButton
                    size="small"
                    icon={<IconGear />}
                    to={urls.settings('environment-access-control')}
                    tooltip="Edit resource access settings"
                    data-attr="access-resolution-edit-resource"
                />
            ),
        },
    ]
    const objectColumns: LemonTableColumns<ResolutionChange> = [
        {
            title: 'Type',
            key: 'type',
            width: 0,
            render: (_, change) => (
                <span className="capitalize whitespace-nowrap">{change.resource.replace(/_/g, ' ')}</span>
            ),
        },
        {
            title: 'Name',
            key: 'object',
            width: 0,
            render: (_, change) => {
                const label = change.object_name ?? change.object_id
                const url = urlForChangeObject(change)
                return (
                    <div className="font-semibold truncate whitespace-nowrap max-w-80" title={label ?? undefined}>
                        {url ? <Link to={url}>{label}</Link> : label}
                    </div>
                )
            },
        },
        ...sharedColumns,
        {
            key: 'actions',
            width: 0,
            render: (_, change) => {
                const url = urlForChangeObject(change)
                return url ? (
                    <LemonButton
                        size="small"
                        icon={<IconExternal />}
                        to={url}
                        tooltip="Open"
                        data-attr="access-resolution-open-object"
                    />
                ) : null
            },
        },
    ]

    return (
        <div className="flex flex-col gap-4">
            <WhyExplainer />
            <div className="flex items-center gap-2">
                {preview.summary.loses > 0 && (
                    <LemonTag type="danger" className="bg-surface-primary">
                        ▼ {preview.summary.loses} rules resolve lower
                    </LemonTag>
                )}
                {preview.summary.gains > 0 && (
                    <LemonTag type="warning" className="bg-surface-primary">
                        ▲ {preview.summary.gains} rules resolve higher
                    </LemonTag>
                )}
            </div>

            {projects.map(([projectId, projectName]) => {
                const projectChanges = preview.changes.filter((change) => change.project_id === projectId)
                const resourceChanges = projectChanges.filter((change) => change.scope === 'resource')
                const objectChanges = projectChanges
                    .filter((change) => change.scope === 'object')
                    .sort(
                        (a, b) =>
                            a.resource.localeCompare(b.resource) ||
                            (a.object_name ?? a.object_id ?? '').localeCompare(b.object_name ?? b.object_id ?? '')
                    )
                return (
                    <div key={projectId} className="flex flex-col gap-2">
                        <h3 className="mb-0">{projectName}</h3>
                        {resourceChanges.length > 0 && (
                            <div>
                                <h4 className="mb-2">Resource-level access</h4>
                                <LemonTable
                                    id={`access-resolution-resource-${projectId}`}
                                    columns={resourceColumns}
                                    dataSource={resourceChanges}
                                    rowKey={(change) =>
                                        `${change.resource}-${change.subject.type}-${change.subject.id}`
                                    }
                                    pagination={{ pageSize: 50, hideOnSinglePage: true }}
                                />
                            </div>
                        )}
                        {objectChanges.length > 0 && (
                            <div>
                                <h4 className="mb-2">Objects with their own access rules</h4>
                                <LemonTable
                                    id={`access-resolution-object-${projectId}`}
                                    columns={objectColumns}
                                    dataSource={objectChanges}
                                    rowKey={(change) =>
                                        `${change.resource}-${change.object_id}-${change.subject.type}-${change.subject.id}`
                                    }
                                    pagination={{ pageSize: 20, hideOnSinglePage: true }}
                                />
                            </div>
                        )}
                    </div>
                )
            })}

            <div className="flex items-center gap-2">
                <LemonButton type="primary" disabledReason="Not available yet" data-attr="access-resolution-accept">
                    Accept the new resolution
                </LemonButton>
                <LemonButton
                    type="secondary"
                    onClick={() => openSupportForm({ kind: 'support' })}
                    data-attr="access-resolution-keep-current"
                >
                    Keep current access
                </LemonButton>
                <span className="text-muted text-xs">
                    Contact support to keep the current access for all members. We will adjust your rules so everyone's
                    effective access stays the same.
                </span>
            </div>
        </div>
    )
}

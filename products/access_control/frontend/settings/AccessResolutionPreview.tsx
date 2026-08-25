import { useActions, useValues } from 'kea'

import {
    LemonBanner,
    LemonButton,
    LemonCollapse,
    LemonTable,
    LemonTableColumns,
    LemonTag,
    Spinner,
} from '@posthog/lemon-ui'

import { supportLogic } from 'lib/components/Support/supportLogic'

import { describeResolutionChange, humanLevel } from './describeResolutionChange'
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

function SubjectCell({ change }: { change: ResolutionChange }): JSX.Element {
    return (
        <div className="flex items-center gap-2 whitespace-nowrap">
            <span className="font-semibold max-w-60 truncate" title={change.subject.name}>
                {change.subject.name}
            </span>
            {change.subject.type === 'role' ? (
                <LemonTag size="small">role</LemonTag>
            ) : change.subject.type === 'everyone' ? (
                <span className="text-muted">(default access)</span>
            ) : null}
        </div>
    )
}

function LevelChangeCell({ change }: { change: ResolutionChange }): JSX.Element {
    return (
        <div className="flex items-center gap-2 whitespace-nowrap">
            <LemonTag>{humanLevel(change.current.level)}</LemonTag>
            <span aria-hidden="true">→</span>
            <LemonTag type={change.direction === 'gains' ? 'warning' : 'danger'}>
                {humanLevel(change.proposed.level)}
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
    const { preview, previewLoading } = useValues(resolutionPreviewLogic)
    const { loadPreview } = useActions(resolutionPreviewLogic)
    const { openSupportForm } = useActions(supportLogic)

    if (previewLoading) {
        return <Spinner className="text-lg" />
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
                    No access rules resolve differently for your organization. Nothing changes when the new resolution
                    takes effect.
                </LemonBanner>
            </div>
        )
    }

    const resourceChanges = preview.changes.filter((change) => change.scope === 'resource')
    const objectChanges = preview.changes.filter((change) => change.scope === 'object')

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
    ]
    const objectColumns: LemonTableColumns<ResolutionChange> = [
        {
            title: 'Object',
            key: 'object',
            width: 0,
            render: (_, change) => (
                <div className="whitespace-nowrap max-w-80">
                    <div className="font-semibold truncate" title={change.object_name ?? change.object_id ?? undefined}>
                        {change.object_name ?? change.object_id}
                    </div>
                    <div className="text-muted text-xs">{change.resource.replace(/_/g, ' ')}</div>
                </div>
            ),
        },
        ...sharedColumns,
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

            {resourceChanges.length > 0 && (
                <div>
                    <h4 className="mb-2">Resource-level access</h4>
                    <LemonTable
                        columns={resourceColumns}
                        dataSource={resourceChanges}
                        rowKey={(change) => `${change.resource}-${change.subject.type}-${change.subject.id}`}
                    />
                </div>
            )}
            {objectChanges.length > 0 && (
                <div>
                    <h4 className="mb-2">Objects with their own access rules</h4>
                    <LemonTable
                        columns={objectColumns}
                        dataSource={objectChanges}
                        rowKey={(change) =>
                            `${change.resource}-${change.object_id}-${change.subject.type}-${change.subject.id}`
                        }
                    />
                </div>
            )}

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

import type { ColumnDef } from '@tanstack/react-table'
import { useActions, useValues } from 'kea'

import { IconExternal, IconGear } from '@posthog/icons'
import {
    Badge,
    Button,
    Collapsible,
    CollapsibleContent,
    CollapsibleTrigger,
    DataTable,
    Heading,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    Skeleton,
    Text,
} from '@posthog/quill'

import { supportLogic } from 'lib/components/Support/supportLogic'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { organizationLogic } from 'scenes/organizationLogic'
import { urls } from 'scenes/urls'

import { humanizeAccessControlLevel } from '~/layout/navigation-3000/sidepanel/panels/access_control/ResourceAccessControlsV2/helpers'
import { AccessControlLevel } from '~/types'

import { describeResolutionChange } from './describeResolutionChange'
import { ResolutionChange, resolutionPreviewLogic } from './resolutionPreviewLogic'
import { urlForChangeObject } from './urlForChangeObject'

const RESOURCE_CHANGES_PER_PAGE = 50
const OBJECT_CHANGES_PER_PAGE = 20

function WhyExplainer(): JSX.Element {
    return (
        <Collapsible>
            <CollapsibleTrigger>Why are we changing this?</CollapsibleTrigger>
            <CollapsibleContent className="flex flex-col gap-2 max-w-200 pt-2">
                <Text size="xs" render={<p className="m-0" />}>
                    We want access control to support both allowlist and denylist setups. For example:
                </Text>
                <Text size="xs" render={<p className="m-0" />}>
                    <strong>Allowlist:</strong> your project is private (No access by default), and you grant specific
                    members or roles access above that. This already works.
                </Text>
                <Text size="xs" render={<p className="m-0" />}>
                    <strong>Denylist:</strong> your project is open to the organization (Member by default), and you
                    want to exclude one role. Today the highest rule applies, so the only way is to set the default to
                    No access and grant access back to everyone else. Once the most specific rule applies, you set No
                    access for that one role and keep the open default.
                </Text>
            </CollapsibleContent>
        </Collapsible>
    )
}

const sharedColumns: ColumnDef<ResolutionChange>[] = [
    {
        id: 'subject',
        header: 'Applies to',
        enableSorting: false,
        cell: ({ row }) => (
            <div className="flex items-center gap-2 whitespace-nowrap">
                <Text
                    size="xs"
                    weight="semibold"
                    render={<span />}
                    className="m-0 max-w-60 truncate"
                    title={row.original.subject.name}
                >
                    {row.original.subject.name}
                </Text>
                <Badge>{row.original.subject.type}</Badge>
            </div>
        ),
    },
    {
        id: 'change',
        header: 'Access',
        enableSorting: false,
        cell: ({ row }) => (
            <div className="flex items-center gap-2 whitespace-nowrap">
                <Badge>{humanizeAccessControlLevel(row.original.current.access_level as AccessControlLevel)}</Badge>
                <span aria-hidden="true">→</span>
                <Badge variant={row.original.direction === 'gains' ? 'warning' : 'destructive'}>
                    {humanizeAccessControlLevel(row.original.proposed.access_level as AccessControlLevel)}
                </Badge>
            </div>
        ),
    },
    {
        id: 'why',
        header: 'Why',
        enableSorting: false,
        meta: { expand: true },
        cell: ({ row }) => (
            <Text size="xs" variant="muted" render={<span />} className="m-0">
                {describeResolutionChange(row.original)}
            </Text>
        ),
    },
]

const resourceColumns: ColumnDef<ResolutionChange>[] = [
    {
        id: 'resource',
        header: 'Setting',
        enableSorting: false,
        cell: ({ row }) => (
            <Text size="xs" weight="semibold" render={<span />} className="m-0 capitalize whitespace-nowrap">
                {row.original.resource.replace(/_/g, ' ')}
            </Text>
        ),
    },
    ...sharedColumns,
    {
        id: 'actions',
        header: '',
        enableSorting: false,
        meta: { align: 'right' },
        cell: ({ row }) => (
            <Button
                size="icon"
                aria-label="Edit resource access settings"
                tooltip="Edit resource access settings"
                nativeButton={false}
                render={
                    <LinkPrimitive
                        to={urls.project(row.original.project_id, urls.settings('environment-access-control'))}
                    />
                }
                data-attr="access-resolution-edit-resource"
            >
                <IconGear />
            </Button>
        ),
    },
]

const objectColumns: ColumnDef<ResolutionChange>[] = [
    {
        id: 'type',
        header: 'Type',
        enableSorting: false,
        cell: ({ row }) => (
            <Text size="xs" render={<span />} className="m-0 capitalize whitespace-nowrap">
                {row.original.resource.replace(/_/g, ' ')}
            </Text>
        ),
    },
    {
        id: 'object',
        header: 'Name',
        enableSorting: false,
        cell: ({ row }) => {
            const label = row.original.object_name ?? row.original.object_id
            const url = urlForChangeObject(row.original)

            return url ? (
                <Button
                    variant="link-foreground"
                    size="sm"
                    className="max-w-80"
                    nativeButton={false}
                    render={<LinkPrimitive to={url} />}
                    title={label ?? undefined}
                >
                    <span className="truncate">{label}</span>
                </Button>
            ) : (
                <Text
                    size="xs"
                    weight="semibold"
                    render={<span />}
                    className="m-0 block max-w-80 truncate whitespace-nowrap"
                    title={label ?? undefined}
                >
                    {label}
                </Text>
            )
        },
    },
    ...sharedColumns,
    {
        id: 'actions',
        header: '',
        enableSorting: false,
        meta: { align: 'right' },
        cell: ({ row }) => {
            const url = urlForChangeObject(row.original)

            return url ? (
                <Button
                    size="icon"
                    aria-label="Open"
                    tooltip="Open"
                    nativeButton={false}
                    render={<LinkPrimitive to={url} />}
                    data-attr="access-resolution-open-object"
                >
                    <IconExternal />
                </Button>
            ) : null
        },
    },
]

export function QuillAccessResolutionPreview({ onAccept }: { onAccept: () => void }): JSX.Element {
    const { preview, previewLoading, previewForbidden, accepted, acceptedLoading } = useValues(resolutionPreviewLogic)
    const { loadPreview } = useActions(resolutionPreviewLogic)
    const { openSupportForm } = useActions(supportLogic)
    const { currentOrganization, isAdminOrOwner } = useValues(organizationLogic)
    // `accepted` keeps the completed state if the organization reload after the switch fails
    const alreadyEnabled = accepted || !!currentOrganization?.uses_most_specific_access_resolution

    if (previewLoading) {
        return (
            <div className="flex flex-col gap-2">
                <Skeleton className="h-8" />
                <Skeleton className="h-32" />
            </div>
        )
    }

    if (previewForbidden) {
        return (
            <Item tone="info" size="sm">
                <ItemContent>
                    <ItemDescription>
                        Only administrators can view the resolution preview. Ask an organization admin to review the
                        changes.
                    </ItemDescription>
                </ItemContent>
            </Item>
        )
    }

    if (!preview) {
        return (
            <Item tone="destructive" size="sm">
                <ItemContent>
                    <ItemDescription>
                        Couldn't load the resolution preview. Try again, and if it keeps happening contact support.
                    </ItemDescription>
                </ItemContent>
                <ItemActions>
                    <Button variant="outline" onClick={() => loadPreview()} data-attr="access-resolution-retry">
                        Try again
                    </Button>
                </ItemActions>
            </Item>
        )
    }

    const footer = alreadyEnabled ? (
        <Item tone="success" size="sm">
            <ItemContent>
                <ItemDescription>Migration completed.</ItemDescription>
            </ItemContent>
        </Item>
    ) : (
        <div className="flex flex-wrap items-center gap-2">
            <Button
                variant="primary"
                onClick={onAccept}
                loading={acceptedLoading}
                disabledReason={isAdminOrOwner ? undefined : 'Only organization admins can switch the resolution'}
                data-attr="access-resolution-accept"
            >
                Accept the new resolution
            </Button>
            <Button
                variant="outline"
                onClick={() => openSupportForm({ kind: 'support' })}
                data-attr="access-resolution-keep-current"
            >
                Keep current access
            </Button>
            <Text size="xs" variant="muted" render={<span />} className="m-0">
                Contact support to keep the current access for all members. We will adjust your rules so everyone's
                effective access stays the same.
            </Text>
        </div>
    )

    if (preview.summary.total === 0) {
        return (
            <div className="flex flex-col gap-4">
                <WhyExplainer />
                <Item tone="success" size="sm">
                    <ItemContent>
                        <ItemDescription>Nothing changes for your organization.</ItemDescription>
                    </ItemContent>
                </Item>
                {footer}
            </div>
        )
    }

    const projects = Array.from(
        new Map(preview.changes.map((change) => [change.project_id, change.project_name])).entries()
    ).sort((a, b) => a[1].localeCompare(b[1]))

    return (
        <div className="flex flex-col gap-4">
            <WhyExplainer />
            <div className="flex flex-wrap items-center gap-2">
                {preview.summary.loses > 0 && (
                    <Badge variant="destructive">{`▼ ${preview.summary.loses} rules resolve lower`}</Badge>
                )}
                {preview.summary.gains > 0 && (
                    <Badge variant="warning">{`▲ ${preview.summary.gains} rules resolve higher`}</Badge>
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
                        <Heading size="sm" render={<h3 className="m-0" />}>
                            {projectName}
                        </Heading>
                        {resourceChanges.length > 0 && (
                            <div id={`access-resolution-resource-${projectId}`} className="flex flex-col gap-2">
                                <Text size="xs" weight="semibold" render={<h4 className="m-0" />}>
                                    Resource-level access
                                </Text>
                                <DataTable
                                    columns={resourceColumns}
                                    data={resourceChanges}
                                    fullWidth
                                    getRowId={(change) =>
                                        `${change.resource}-${change.subject.type}-${change.subject.id}`
                                    }
                                    pageSize={
                                        resourceChanges.length > RESOURCE_CHANGES_PER_PAGE
                                            ? RESOURCE_CHANGES_PER_PAGE
                                            : undefined
                                    }
                                />
                            </div>
                        )}
                        {objectChanges.length > 0 && (
                            <div id={`access-resolution-object-${projectId}`} className="flex flex-col gap-2">
                                <Text size="xs" weight="semibold" render={<h4 className="m-0" />}>
                                    Objects with their own access rules
                                </Text>
                                <DataTable
                                    columns={objectColumns}
                                    data={objectChanges}
                                    fullWidth
                                    getRowId={(change) =>
                                        `${change.resource}-${change.object_id}-${change.subject.type}-${change.subject.id}`
                                    }
                                    pageSize={
                                        objectChanges.length > OBJECT_CHANGES_PER_PAGE
                                            ? OBJECT_CHANGES_PER_PAGE
                                            : undefined
                                    }
                                />
                            </div>
                        )}
                    </div>
                )
            })}

            {footer}
        </div>
    )
}

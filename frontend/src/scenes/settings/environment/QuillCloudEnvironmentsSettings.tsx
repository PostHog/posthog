import { useActions, useValues } from 'kea'

import { IconEllipsis, IconPlus } from '@posthog/icons'
import {
    Badge,
    Button,
    DataTable,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuTrigger,
    Empty,
    EmptyDescription,
    EmptyHeader,
    Skeleton,
    Text,
} from '@posthog/quill'

import { LemonMenuItems } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { QuillMenuItems } from 'scenes/session-recordings/playlist/QuillMenuItems'

import type { SandboxEnvironmentDTOApi } from 'products/tasks/frontend/generated/api.schemas'

import { networkAccessLabel } from './cloudEnvironmentNetworkAccess'
import { cloudEnvironmentsLogic } from './cloudEnvironmentsLogic'
import { QuillCloudEnvironmentModal } from './QuillCloudEnvironmentModal'
import { QuillLoadFailedCallout } from './QuillLoadFailedCallout'

export function QuillCloudEnvironmentsSettings({
    actionItems,
}: {
    actionItems: (environment: SandboxEnvironmentDTOApi) => LemonMenuItems
}): JSX.Element {
    const { environments, environmentsLoading, environmentsFailed } = useValues(cloudEnvironmentsLogic)
    const { loadEnvironments, startNewEnvironment } = useActions(cloudEnvironmentsLogic)

    return (
        <div className="flex flex-col gap-2 max-w-200">
            <div className="flex">
                <Button variant="primary" onClick={startNewEnvironment} data-attr="cloud-environment-new">
                    <IconPlus />
                    New environment
                </Button>
            </div>
            {environmentsFailed ? (
                <QuillLoadFailedCallout
                    message="The environments did not load."
                    onRetry={loadEnvironments}
                    loading={environmentsLoading}
                />
            ) : environmentsLoading && environments === null ? (
                <Skeleton className="h-24 w-full" />
            ) : (
                <DataTable
                    size="sm"
                    fullWidth
                    data={environments ?? []}
                    getRowId={(environment) => environment.id}
                    empty={
                        <Empty>
                            <EmptyHeader>
                                <EmptyDescription>
                                    No environments yet. Cloud runs have full network access until you add one.
                                </EmptyDescription>
                            </EmptyHeader>
                        </Empty>
                    }
                    columns={[
                        {
                            id: 'name',
                            header: 'Name',
                            enableSorting: false,
                            meta: { expand: true },
                            cell: ({ row }) => (
                                <div className="flex flex-wrap items-center gap-1">
                                    <Text size="xs" weight="semibold" render={<span />}>
                                        {row.original.name}
                                    </Text>
                                    {row.original.internal ? <Badge>Internal</Badge> : null}
                                </div>
                            ),
                        },
                        {
                            id: 'private',
                            header: 'Used by',
                            enableSorting: false,
                            cell: ({ row }) => (
                                <Badge variant={row.original.private ? 'default' : 'warning'}>
                                    {row.original.private ? 'Only you' : 'Everyone in this project'}
                                </Badge>
                            ),
                        },
                        {
                            id: 'network_access_level',
                            header: 'Network access',
                            enableSorting: false,
                            cell: ({ row }) => networkAccessLabel(row.original.network_access_level),
                        },
                        {
                            id: 'repositories',
                            header: 'Repositories',
                            enableSorting: false,
                            cell: ({ row }) =>
                                row.original.repositories?.length ? (
                                    <span translate="no">{row.original.repositories.join(', ')}</span>
                                ) : (
                                    <Text size="xs" variant="muted" render={<span />}>
                                        Any repository
                                    </Text>
                                ),
                        },
                        {
                            id: 'custom_image_name',
                            header: 'Image',
                            enableSorting: false,
                            cell: ({ row }) =>
                                row.original.custom_image_name ? (
                                    <span>{row.original.custom_image_name}</span>
                                ) : (
                                    <Text size="xs" variant="muted" render={<span />}>
                                        Default
                                    </Text>
                                ),
                        },
                        {
                            id: 'actions',
                            header: '',
                            enableSorting: false,
                            meta: { align: 'right' },
                            cell: ({ row }) =>
                                row.original.internal ? null : (
                                    <DropdownMenu>
                                        <DropdownMenuTrigger
                                            render={
                                                <Button
                                                    size="icon"
                                                    aria-label={`Actions for ${row.original.name}`}
                                                    tooltip={`Actions for ${row.original.name}`}
                                                />
                                            }
                                        >
                                            <IconEllipsis />
                                        </DropdownMenuTrigger>
                                        <DropdownMenuContent align="end">
                                            <QuillMenuItems items={actionItems(row.original)} />
                                        </DropdownMenuContent>
                                    </DropdownMenu>
                                ),
                        },
                    ]}
                />
            )}
            <QuillCloudEnvironmentModal />
        </div>
    )
}

import type { ColumnDef } from '@tanstack/react-table'
import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconArrowLeft } from '@posthog/icons'
import { Badge, Button, DataTable, Heading, Skeleton, Text } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { organizationLogic } from 'scenes/organizationLogic'
import { QuillTagList } from 'scenes/settings/user/QuillTagList'

import type { ServiceAccountAPIKeyApi } from '~/generated/core/api.schemas'

import { ServiceAccountLogicProps, serviceAccountLogic } from './serviceAccountLogic'
import { serviceAccountsLogic } from './serviceAccountsLogic'

export function QuillServiceAccountDetails(props: ServiceAccountLogicProps): JSX.Element {
    const logic = serviceAccountLogic(props)
    const { account, accountLoading, accountLoadFailed, apiKeys, apiKeysLoading, keysLoadFailed } = useValues(logic)
    const { loadAccount, loadApiKeys } = useActions(logic)
    const { selectAccount } = useActions(serviceAccountsLogic({ organizationId: props.organizationId }))
    const { currentOrganization } = useValues(organizationLogic)
    const columns = useMemo<ColumnDef<ServiceAccountAPIKeyApi>[]>(
        () => [
            {
                accessorKey: 'label',
                header: 'Key',
                cell: ({ row: { original: key } }) => (
                    <div className="flex flex-col gap-1">
                        <Text className="break-words" weight="medium">
                            {key.label}
                        </Text>
                        <code>{key.mask_value}</code>
                        <Text size="xs" variant="muted">
                            Created <TZLabel time={key.created_at} />
                        </Text>
                        <Text size="xs" variant="muted">
                            {key.expires_at ? (
                                <>
                                    Expires <TZLabel time={key.expires_at} />
                                </>
                            ) : (
                                'Never expires'
                            )}
                        </Text>
                    </div>
                ),
            },
            {
                id: 'access',
                header: 'Access',
                cell: ({ row: { original: key } }) => (
                    <div className="flex flex-col gap-2">
                        <QuillTagList tags={[...key.scopes]} />
                        <Text size="xs" variant="muted">
                            {key.scoped_organizations?.length &&
                            !key.scoped_organizations.includes(props.organizationId)
                                ? 'No access to this organization'
                                : key.scoped_teams?.length
                                  ? key.scoped_teams
                                        .map(
                                            (id) =>
                                                currentOrganization?.teams.find((team) => team.id === id)?.name ??
                                                `Project ${id}`
                                        )
                                        .join(', ')
                                  : 'All projects the account can access'}
                        </Text>
                    </div>
                ),
            },
            {
                accessorKey: 'last_used_at',
                header: 'Last used',
                cell: ({ row }) => (row.original.last_used_at ? <TZLabel time={row.original.last_used_at} /> : 'Never'),
            },
        ],
        [currentOrganization, props.organizationId]
    )

    return (
        <div data-quill className="flex flex-col gap-4">
            <Button
                variant="link-foreground"
                onClick={() => selectAccount(null)}
                data-attr="service-account-back"
                className="self-start"
            >
                <IconArrowLeft />
                All service accounts
            </Button>
            {accountLoadFailed && !accountLoading ? (
                <div role="alert">
                    <Text size="xs">
                        Couldn't load this service account. It may no longer be available. Try again or return to the
                        list.
                    </Text>
                    <Button onClick={loadAccount}>Retry</Button>
                </div>
            ) : account === null ? (
                <Skeleton className="h-16" />
            ) : (
                <>
                    <div className="flex flex-wrap items-center gap-2">
                        <Heading render={<h3 className="m-0" />} className="break-words">
                            {account.name}
                        </Heading>
                        <Badge variant={account.is_active ? 'success' : 'default'}>
                            {account.is_active ? 'Active' : 'Disabled'}
                        </Badge>
                    </div>
                    <Text size="xs" variant="muted">
                        Created <TZLabel time={account.created_at} />
                    </Text>
                    <Heading render={<h4 className="m-0" />}>API keys</Heading>
                    <Text size="xs">
                        Keys authenticate as this service account. Each key can limit its API scopes and project access.
                        Only masked values are shown.
                    </Text>
                    {keysLoadFailed && !apiKeysLoading ? (
                        <div role="alert">
                            <Text size="xs">Couldn't load API keys. Try again.</Text>
                            <Button onClick={loadApiKeys}>Retry</Button>
                        </div>
                    ) : apiKeys === null ? (
                        <Skeleton className="h-32" />
                    ) : (
                        <DataTable
                            data={apiKeys}
                            columns={columns}
                            fullWidth
                            getRowId={(key) => key.id}
                            pageSize={20}
                            empty={<Text size="xs">This service account has no API keys.</Text>}
                        />
                    )}
                </>
            )}
        </div>
    )
}

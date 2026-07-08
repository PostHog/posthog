import { useActions, useValues } from 'kea'

import { LemonInput } from '@posthog/lemon-ui'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { TZLabel } from 'lib/components/TZLabel'
import { OrganizationMembershipLevel } from 'lib/constants'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { fullName } from 'lib/utils/strings'
import { TagList } from 'scenes/settings/user/PersonalAPIKeys'

import { AvailableFeature } from '~/types'

import type { OrganizationPersonalAPIKeyApi } from 'products/platform_features/frontend/generated/api.schemas'

import { organizationPersonalAPIKeysLogic } from './organizationPersonalAPIKeysLogic'

function AccessScope({ accessScope }: { accessScope: OrganizationPersonalAPIKeyApi['access_scope'] }): JSX.Element {
    if (accessScope.type === 'all') {
        return <span className="text-muted">All projects (unscoped)</span>
    }
    if (accessScope.type === 'organization') {
        return <span>Organization-wide</span>
    }
    return <TagList tags={(accessScope.projects ?? []).map((project) => project.name)} />
}

function ownerLabel(owner: OrganizationPersonalAPIKeyApi['owner']): string {
    return fullName(owner) || owner.email
}

export function OrganizationPersonalAPIKeys(): JSX.Element {
    const { filteredKeys, keysLoading, search } = useValues(organizationPersonalAPIKeysLogic)
    const { setSearch } = useActions(organizationPersonalAPIKeysLogic)
    const restrictionReason = useRestrictedArea({ minimumAccessLevel: OrganizationMembershipLevel.Admin })

    if (restrictionReason) {
        return <p className="text-muted">{restrictionReason}</p>
    }

    const columns: LemonTableColumns<OrganizationPersonalAPIKeyApi> = [
        {
            title: 'Owner',
            key: 'owner',
            sorter: (a, b) => ownerLabel(a.owner).localeCompare(ownerLabel(b.owner)),
            render: (_, key) => (
                <div className="flex flex-col">
                    <span>{ownerLabel(key.owner)}</span>
                    <span className="text-muted text-xs">{key.owner.email}</span>
                </div>
            ),
        },
        {
            title: 'Masked value',
            key: 'mask_value',
            sorter: (a, b) => a.mask_value.localeCompare(b.mask_value),
            render: (_, key) => <span className="font-mono">{key.mask_value}</span>,
        },
        {
            title: 'Scopes',
            key: 'scopes',
            render: (_, key) => <TagList tags={[...key.scopes]} />,
        },
        {
            title: 'Access scope',
            key: 'access_scope',
            render: (_, key) => <AccessScope accessScope={key.access_scope} />,
        },
        {
            title: 'Last used',
            key: 'last_used_at',
            sorter: (a, b) => new Date(a.last_used_at ?? 0).getTime() - new Date(b.last_used_at ?? 0).getTime(),
            render: (_, key) =>
                key.last_used_at ? <TZLabel time={key.last_used_at} /> : <span className="text-muted">Never</span>,
        },
        {
            title: 'Created',
            key: 'created_at',
            sorter: (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
            render: (_, key) => <TZLabel time={key.created_at} />,
        },
    ]

    return (
        <PayGateMini feature={AvailableFeature.ORGANIZATION_SECURITY_SETTINGS}>
            <div className="mb-2">
                <LemonInput
                    type="search"
                    placeholder="Search by name, email, or scope"
                    value={search}
                    onChange={setSearch}
                    className="max-w-80"
                />
            </div>
            <LemonTable
                dataSource={filteredKeys}
                loading={keysLoading}
                columns={columns}
                rowKey={(key) => `${key.owner.email}-${key.mask_value}-${key.created_at}`}
                pagination={{ pageSize: 25 }}
                emptyState={
                    search.trim()
                        ? 'No personal API keys match your search.'
                        : 'No personal API keys have access to this organization.'
                }
            />
        </PayGateMini>
    )
}

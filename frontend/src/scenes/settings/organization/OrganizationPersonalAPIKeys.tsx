import { useValues } from 'kea'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { TZLabel } from 'lib/components/TZLabel'
import { OrganizationMembershipLevel } from 'lib/constants'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
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

function ownerName(owner: OrganizationPersonalAPIKeyApi['owner']): string {
    return [owner.first_name, owner.last_name].filter(Boolean).join(' ') || owner.email
}

export function OrganizationPersonalAPIKeys(): JSX.Element {
    const { keys, keysLoading } = useValues(organizationPersonalAPIKeysLogic)
    const restrictionReason = useRestrictedArea({ minimumAccessLevel: OrganizationMembershipLevel.Admin })

    if (restrictionReason) {
        return <p className="text-muted">{restrictionReason}</p>
    }

    const columns: LemonTableColumns<OrganizationPersonalAPIKeyApi> = [
        {
            title: 'Owner',
            key: 'owner',
            render: (_, key) => (
                <div className="flex flex-col">
                    <span>{ownerName(key.owner)}</span>
                    <span className="text-muted text-xs">{key.owner.email}</span>
                </div>
            ),
        },
        {
            title: 'Masked value',
            key: 'mask_value',
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
            render: (_, key) =>
                key.last_used_at ? <TZLabel time={key.last_used_at} /> : <span className="text-muted">Never</span>,
        },
        {
            title: 'Created',
            key: 'created_at',
            render: (_, key) => <TZLabel time={key.created_at} />,
        },
    ]

    return (
        <PayGateMini feature={AvailableFeature.ORGANIZATION_SECURITY_SETTINGS}>
            <LemonTable
                dataSource={keys}
                loading={keysLoading}
                columns={columns}
                rowKey={(key) => `${key.owner.email}-${key.mask_value}`}
                emptyState="No personal API keys have access to this organization."
            />
        </PayGateMini>
    )
}

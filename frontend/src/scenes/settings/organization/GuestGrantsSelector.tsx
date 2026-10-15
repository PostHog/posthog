import { useActions, useValues } from 'kea'

import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonSelect } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { GuestGrant, inviteLogic } from './inviteLogic'

const RESOURCE_OPTIONS: { value: GuestGrant['resource']; label: string }[] = [
    { value: 'dashboard', label: 'Dashboards' },
    { value: 'insight', label: 'Insights' },
    { value: 'notebook', label: 'Notebooks' },
]

const GROUP_TYPES: Record<GuestGrant['resource'], TaxonomicFilterGroupType> = {
    dashboard: TaxonomicFilterGroupType.Dashboards,
    insight: TaxonomicFilterGroupType.Insights,
    notebook: TaxonomicFilterGroupType.Notebooks,
}

export function GuestGrantsSelector({ inviteIndex }: { inviteIndex: number }): JSX.Element {
    const { invitesToSend } = useValues(inviteLogic)
    const { updateInviteAtIndex } = useActions(inviteLogic)
    const grants = invitesToSend[inviteIndex]?.guest_grants ?? []

    const setGrants = (guest_grants: GuestGrant[]): void => updateInviteAtIndex({ guest_grants }, inviteIndex)
    const updateGrant = (grantIndex: number, grant: GuestGrant): void =>
        setGrants(grants.map((existing, index) => (index === grantIndex ? grant : existing)))

    return (
        <div className="space-y-2" data-attr="invite-guest-grants">
            <div className="font-semibold">What this guest can view</div>
            <div className="text-secondary text-xs">Guests can only view what you choose here, in this project.</div>
            {grants.map((grant, grantIndex) => (
                <div key={grantIndex} className="flex gap-2 items-center">
                    <LemonSelect
                        size="small"
                        options={RESOURCE_OPTIONS}
                        value={grant.resource}
                        onChange={(resource) => updateGrant(grantIndex, { resource, id: null })}
                    />
                    <LemonSelect
                        size="small"
                        options={[
                            { value: 'all', label: 'All of them' },
                            { value: 'one', label: 'One of them' },
                        ]}
                        value={grant.id === null && grant.name === undefined ? 'all' : 'one'}
                        onChange={(scope) =>
                            updateGrant(grantIndex, {
                                resource: grant.resource,
                                id: null,
                                name: scope === 'one' ? '' : undefined,
                            })
                        }
                    />
                    {grant.name !== undefined && (
                        <TaxonomicPopover
                            size="small"
                            groupType={GROUP_TYPES[grant.resource]}
                            value={grant.name || null}
                            placeholder="Choose one"
                            onChange={(_value, _groupType, item) =>
                                updateGrant(grantIndex, {
                                    resource: grant.resource,
                                    id: String(item.id),
                                    name: item.name || item.title || String(item.id),
                                })
                            }
                            renderValue={() => <span>{grant.name}</span>}
                        />
                    )}
                    <LemonButton
                        size="small"
                        icon={<IconTrash />}
                        status="danger"
                        onClick={() => setGrants(grants.filter((_, index) => index !== grantIndex))}
                        tooltip="Remove this access"
                    />
                </div>
            ))}
            <LemonButton
                size="small"
                type="secondary"
                icon={<IconPlus />}
                onClick={() => setGrants([...grants, { resource: 'dashboard', id: null }])}
                data-attr="invite-guest-add-grant"
            >
                Add access
            </LemonButton>
        </div>
    )
}

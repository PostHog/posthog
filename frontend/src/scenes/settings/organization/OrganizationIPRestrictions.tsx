import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSwitch, LemonTag } from '@posthog/lemon-ui'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature } from '~/types'

import { isIpAllowed, isValidIpAddress, isValidIpOrCidr } from './ipRestrictionsUtils'

const MAX_IP_RESTRICTIONS = 100

export function OrganizationIPRestrictions(): JSX.Element {
    const { currentOrganization, currentOrganizationLoading: saving } = useValues(organizationLogic)
    const { updateOrganization } = useActions(organizationLogic)
    const { hasAvailableFeature } = useValues(userLogic)
    const restrictionReason = useRestrictedArea({ minimumAccessLevel: OrganizationMembershipLevel.Admin })
    const canConfigure = hasAvailableFeature(AvailableFeature.IP_RESTRICTIONS)
    const entries = currentOrganization?.ip_restrictions ?? []
    const enabled = currentOrganization?.ip_restrictions_enabled ?? false
    const canEdit = !restrictionReason && !saving && canConfigure

    const [newEntry, setNewEntry] = useState('')
    const [newEntryError, setNewEntryError] = useState<string | null>(null)
    const [testIp, setTestIp] = useState('')
    const [testResult, setTestResult] = useState<boolean | null>(null)

    const addEntry = (): void => {
        if (!canEdit) {
            return
        }
        const entry = newEntry.trim()
        if (!isValidIpOrCidr(entry)) {
            setNewEntryError('Enter a valid IP address or CIDR block, such as 203.0.113.4 or 10.0.0.0/8.')
            return
        }
        if (entries.includes(entry)) {
            setNewEntryError('That IP address or CIDR block is already in the list.')
            return
        }
        if (entries.length >= MAX_IP_RESTRICTIONS) {
            setNewEntryError(`You can add at most ${MAX_IP_RESTRICTIONS} IP addresses or CIDR blocks.`)
            return
        }
        setNewEntry('')
        setNewEntryError(null)
        setTestResult(null)
        updateOrganization({ ip_restrictions: [...entries, entry], ip_restrictions_enabled: enabled })
    }

    return (
        <PayGateMini
            feature={AvailableFeature.IP_RESTRICTIONS}
            featureDetail="organization-ip-restrictions"
            overrideShouldShowGate={enabled}
        >
            <div className="flex flex-col gap-4">
                <LemonSwitch
                    label="Enable IP restrictions"
                    bordered
                    checked={enabled}
                    onChange={(nextEnabled) => updateOrganization({ ip_restrictions_enabled: nextEnabled })}
                    loading={saving}
                    disabledReason={restrictionReason}
                    data-attr="ip-restrictions-enabled-toggle"
                />
                <div className="flex flex-wrap items-end gap-2">
                    <LemonInput
                        className="min-w-72"
                        placeholder="203.0.113.4 or 10.0.0.0/8"
                        value={newEntry}
                        onChange={(value) => {
                            setNewEntry(value)
                            setNewEntryError(null)
                        }}
                        onPressEnter={addEntry}
                        disabled={!canEdit}
                        data-attr="ip-restrictions-input"
                    />
                    <LemonButton
                        type="secondary"
                        icon={<IconPlusSmall />}
                        onClick={addEntry}
                        loading={saving}
                        disabledReason={
                            restrictionReason ||
                            (!canConfigure ? 'Upgrade your plan to add IP restrictions' : null) ||
                            (entries.length >= MAX_IP_RESTRICTIONS ? 'List is full' : null)
                        }
                    >
                        Add
                    </LemonButton>
                </div>
                {newEntryError && <p className="text-danger text-sm m-0">{newEntryError}</p>}

                {entries.length === 0 ? (
                    <p className="text-muted m-0">
                        You have no IP restrictions. Members of your organization can access PostHog from any IP
                        address.
                    </p>
                ) : (
                    <div className="flex flex-wrap gap-1">
                        {entries.map((entry) => (
                            <LemonTag
                                key={entry}
                                closable={canEdit}
                                onClose={() => {
                                    setTestResult(null)
                                    updateOrganization({
                                        ip_restrictions: entries.filter((current) => current !== entry),
                                        ip_restrictions_enabled: enabled,
                                    })
                                }}
                            >
                                {entry}
                            </LemonTag>
                        ))}
                    </div>
                )}

                <div className="flex flex-col gap-2">
                    <h4 className="m-0">Test an IP address</h4>
                    <div className="flex flex-wrap items-center gap-2">
                        <LemonInput
                            className="min-w-72"
                            placeholder="203.0.113.4"
                            value={testIp}
                            onChange={(value) => {
                                setTestIp(value)
                                setTestResult(null)
                            }}
                            data-attr="ip-restrictions-test-input"
                        />
                        <LemonButton
                            type="secondary"
                            onClick={() => setTestResult(isIpAllowed(testIp, entries))}
                            disabledReason={!isValidIpAddress(testIp) ? 'Enter a valid IP address' : null}
                            data-attr="ip-restrictions-test"
                        >
                            Test
                        </LemonButton>
                    </div>
                    {testResult !== null && (
                        <p className={testResult ? 'text-success m-0' : 'text-danger m-0'}>
                            {entries.length === 0
                                ? 'No rules are configured, so every IP address is allowed.'
                                : testResult
                                  ? `${testIp} is allowed by this list.`
                                  : `${testIp} would be blocked by this list.`}
                        </p>
                    )}
                </div>
            </div>
        </PayGateMini>
    )
}

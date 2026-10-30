import ipaddr from 'ipaddr.js'
import { useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSwitch, LemonTag } from '@posthog/lemon-ui'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { organizationLogic } from 'scenes/organizationLogic'

import { AvailableFeature, OrganizationType } from '~/types'

const MAX_IP_RESTRICTIONS = 100

function isValidIpOrCidr(value: string): boolean {
    const trimmed = value.trim()
    if (!trimmed) {
        return false
    }
    try {
        ipaddr.parseCIDR(trimmed)
        return true
    } catch {
        return ipaddr.isValid(trimmed)
    }
}

function parseRestriction(restriction: string): [ipaddr.IPv4 | ipaddr.IPv6, number] | null {
    const trimmed = restriction.trim()
    try {
        return ipaddr.parseCIDR(trimmed)
    } catch {
        try {
            const address = ipaddr.parse(trimmed)
            return [address, address.kind() === 'ipv6' ? 128 : 32]
        } catch {
            return null
        }
    }
}

function isIpAllowed(ip: string, restrictions: string[]): boolean {
    if (restrictions.length === 0) {
        return true
    }
    try {
        const address = ipaddr.parse(ip.trim())
        return restrictions.some((restriction) => {
            const parsed = parseRestriction(restriction)
            return parsed !== null && parsed[0].kind() === address.kind() && address.match(parsed[0], parsed[1])
        })
    } catch {
        return false
    }
}

export function OrganizationIPRestrictions(): JSX.Element {
    const { currentOrganization } = useValues(organizationLogic)
    const restrictionReason = useRestrictedArea({ minimumAccessLevel: OrganizationMembershipLevel.Admin })

    const [entries, setEntries] = useState<string[]>(currentOrganization?.ip_restrictions ?? [])
    const [enabled, setEnabled] = useState(currentOrganization?.ip_restrictions_enabled ?? false)
    const [togglingEnabled, setTogglingEnabled] = useState(false)
    const [newEntry, setNewEntry] = useState('')
    const [newEntryError, setNewEntryError] = useState<string | null>(null)
    const [testIp, setTestIp] = useState('')
    const [testResult, setTestResult] = useState<boolean | null>(null)
    const [saving, setSaving] = useState(false)

    useEffect(() => {
        setEntries(currentOrganization?.ip_restrictions ?? [])
    }, [currentOrganization?.ip_restrictions])

    useEffect(() => {
        setEnabled(currentOrganization?.ip_restrictions_enabled ?? false)
    }, [currentOrganization?.ip_restrictions_enabled])

    const showWarning = (organization: OrganizationType | null | undefined): void => {
        if (organization?.ip_restrictions_warning) {
            lemonToast.warning(organization.ip_restrictions_warning)
        }
    }

    const toggleEnabled = async (nextEnabled: boolean): Promise<void> => {
        setEnabled(nextEnabled)
        setTogglingEnabled(true)
        try {
            const updated = await organizationLogic.asyncActions.updateOrganization({
                ip_restrictions_enabled: nextEnabled,
            })
            showWarning(updated)
        } catch {
            setEnabled(!nextEnabled)
        } finally {
            setTogglingEnabled(false)
        }
    }

    const persistEntries = async (nextEntries: string[]): Promise<void> => {
        const previousEntries = entries
        setEntries(nextEntries)
        setSaving(true)
        try {
            const updated = await organizationLogic.asyncActions.updateOrganization({ ip_restrictions: nextEntries })
            showWarning(updated)
        } catch {
            setEntries(previousEntries)
        } finally {
            setSaving(false)
        }
    }

    const addEntry = (): void => {
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
        void persistEntries([...entries, entry])
    }

    return (
        <PayGateMini feature={AvailableFeature.IP_RESTRICTIONS} featureDetail="organization-ip-restrictions">
            <div className="flex flex-col gap-4">
                <LemonSwitch
                    label="Enable IP restrictions"
                    bordered
                    checked={enabled}
                    onChange={(nextEnabled) => void toggleEnabled(nextEnabled)}
                    loading={togglingEnabled}
                    disabledReason={restrictionReason}
                    data-attr="ip-restrictions-enabled-toggle"
                />
                {enabled && (
                    <>
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
                                disabled={!!restrictionReason || saving}
                                data-attr="ip-restrictions-input"
                            />
                            <LemonButton
                                type="secondary"
                                icon={<IconPlusSmall />}
                                onClick={addEntry}
                                disabledReason={
                                    restrictionReason || (entries.length >= MAX_IP_RESTRICTIONS ? 'List is full' : null)
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
                                        closable={!restrictionReason && !saving}
                                        onClose={() => {
                                            setEntries(entries.filter((current) => current !== entry))
                                            setTestResult(null)
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
                                    disabledReason={!isValidIpOrCidr(testIp) ? 'Enter a valid IP address' : null}
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
                    </>
                )}
            </div>
        </PayGateMini>
    )
}

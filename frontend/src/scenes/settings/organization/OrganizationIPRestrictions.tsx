import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonButton, LemonInput, LemonLabel, LemonSkeleton, LemonSwitch } from '@posthog/lemon-ui'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'

import { AvailableFeature } from '~/types'

import { isIpAllowed, isValidIpAddress } from './ipRestrictionsUtils'
import { organizationIPRestrictionsLogic } from './organizationIPRestrictionsLogic'

export function OrganizationIPRestrictions(): JSX.Element {
    const {
        currentOrganization,
        currentOrganizationLoading: saving,
        enabled,
        values,
        cleaned,
        validationError,
        editDisabledReason,
        saveDisabledReason,
        toggleDisabledReason,
    } = useValues(organizationIPRestrictionsLogic)
    const { setDraftEntries, save, setEnabled } = useActions(organizationIPRestrictionsLogic)
    const [testIp, setTestIp] = useState('')
    const [testResult, setTestResult] = useState<boolean | null>(null)

    useEffect(() => {
        setTestResult(null)
    }, [currentOrganization])

    if (!currentOrganization) {
        return <LemonSkeleton className="h-20" />
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
                    onChange={setEnabled}
                    loading={saving}
                    disabledReason={toggleDisabledReason}
                    data-attr="ip-restrictions-enabled-toggle"
                />
                <LemonLabel htmlFor="ip-restrictions-list">Allowed IP addresses and CIDR blocks</LemonLabel>
                <LemonInputSelect
                    id="ip-restrictions-list"
                    mode="multiple"
                    allowCustomValues
                    value={values}
                    onChange={(nextEntries) => {
                        setDraftEntries(nextEntries, currentOrganization.id)
                        setTestResult(null)
                    }}
                    placeholder="203.0.113.4 or 10.0.0.0/8"
                    loading={saving}
                    disabled={saving}
                    disabledReason={editDisabledReason}
                    status={validationError ? 'danger' : 'default'}
                    data-attr="ip-restrictions-input"
                    fullWidth
                />
                {validationError && <p className="text-danger text-sm m-0">{validationError}</p>}
                {values.length === 0 && (
                    <p className="text-muted m-0">
                        With no IP restrictions, members of your organization can access PostHog from any IP address.
                    </p>
                )}
                <LemonButton
                    type="primary"
                    className="self-start"
                    onClick={save}
                    loading={saving}
                    disabledReason={saveDisabledReason}
                    data-attr="ip-restrictions-save"
                >
                    Save
                </LemonButton>

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
                            onClick={() => setTestResult(isIpAllowed(testIp, cleaned))}
                            disabledReason={
                                validationError || (!isValidIpAddress(testIp) ? 'Enter a valid IP address' : null)
                            }
                            data-attr="ip-restrictions-test"
                        >
                            Test
                        </LemonButton>
                    </div>
                    {testResult !== null && (
                        <p className={testResult ? 'text-success m-0' : 'text-danger m-0'}>
                            {cleaned.length === 0
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

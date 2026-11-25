import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonButton, LemonInput, LemonLabel, LemonSkeleton, LemonSwitch } from '@posthog/lemon-ui'
import { Skeleton } from '@posthog/quill'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'

import { AvailableFeature } from '~/types'

import { isIpAllowed, isValidIpAddress } from './ipRestrictionsUtils'
import { organizationIPRestrictionsLogic } from './organizationIPRestrictionsLogic'
import { QuillOrganizationIPRestrictions } from './QuillOrganizationIPRestrictions'

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
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    useEffect(() => {
        setTestResult(null)
    }, [currentOrganization])

    if (!currentOrganization) {
        return todayRailNav ? <Skeleton className="h-20" /> : <LemonSkeleton className="h-20" />
    }

    const handleEntriesChange = (nextEntries: string[]): void => {
        setDraftEntries(nextEntries, currentOrganization.id)
        setTestResult(null)
    }

    const handleTestIpChange = (value: string): void => {
        setTestIp(value)
        setTestResult(null)
    }

    const runTest = (): void => setTestResult(isIpAllowed(testIp, cleaned))

    const testDisabledReason = validationError || (!isValidIpAddress(testIp) ? 'Enter a valid IP address' : null)

    const testResultMessage =
        cleaned.length === 0
            ? 'No rules are configured, so every IP address is allowed.'
            : testResult
              ? `${testIp} is allowed by this list.`
              : `${testIp} would be blocked by this list.`

    if (todayRailNav) {
        return (
            <PayGateMini
                feature={AvailableFeature.IP_RESTRICTIONS}
                featureDetail="organization-ip-restrictions"
                overrideShouldShowGate={enabled}
            >
                <QuillOrganizationIPRestrictions
                    testIp={testIp}
                    testResult={testResult}
                    testResultMessage={testResultMessage}
                    testDisabledReason={testDisabledReason}
                    onEntriesChange={handleEntriesChange}
                    onTestIpChange={handleTestIpChange}
                    onTest={runTest}
                />
            </PayGateMini>
        )
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
                    onChange={handleEntriesChange}
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
                            onChange={handleTestIpChange}
                            data-attr="ip-restrictions-test-input"
                        />
                        <LemonButton
                            type="secondary"
                            onClick={runTest}
                            disabledReason={testDisabledReason}
                            data-attr="ip-restrictions-test"
                        >
                            Test
                        </LemonButton>
                    </div>
                    {testResult !== null && (
                        <p className={testResult ? 'text-success m-0' : 'text-danger m-0'}>{testResultMessage}</p>
                    )}
                </div>
            </div>
        </PayGateMini>
    )
}

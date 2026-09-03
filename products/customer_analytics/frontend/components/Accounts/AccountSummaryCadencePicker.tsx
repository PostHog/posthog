import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { SlackSummaryCadenceEnumApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { accountSummariesLogic } from './accountSummariesLogic'

const CADENCE_OPTIONS: { value: SlackSummaryCadenceEnumApi | null; label: string }[] = [
    { value: null, label: 'Off' },
    { value: SlackSummaryCadenceEnumApi.Daily, label: 'Daily' },
    { value: SlackSummaryCadenceEnumApi.Weekly, label: 'Weekly' },
    { value: SlackSummaryCadenceEnumApi.Monthly, label: 'Monthly' },
]

export function AccountSummaryCadencePicker({ accountId }: { accountId: string }): JSX.Element {
    const logic = accountSummariesLogic({ accountId })
    const { summariesResult, cadenceSaving } = useValues(logic)
    const { setCadence } = useActions(logic)

    return (
        <LemonSelect<SlackSummaryCadenceEnumApi | null>
            size="small"
            value={summariesResult.cadence}
            options={CADENCE_OPTIONS}
            onChange={setCadence}
            disabledReason={cadenceSaving ? 'Saving…' : undefined}
            data-attr="account-summary-cadence-picker"
        />
    )
}

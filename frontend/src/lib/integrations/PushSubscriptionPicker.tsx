import { useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import { LemonInputSelect, LemonInputSelectOption } from '@posthog/lemon-ui'

import { ApiRequest } from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

export type PushSubscriptionSafeType = {
    id: string
    distinct_id: string
    platform: 'android' | 'ios' | 'web'
    is_active: boolean
    created_at: string
    updated_at: string
    person_id: number | null
    person_email: string | null
    person_name: string | null
}

export type PushSubscriptionPickerProps = {
    value?: string
    onChange?: (value: string | null) => void
    disabled?: boolean
    platform?: 'android' | 'ios' | 'web'
}

export function PushSubscriptionPicker({
    onChange,
    value,
    disabled,
    platform,
}: PushSubscriptionPickerProps): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const [subscriptions, setSubscriptions] = useState<PushSubscriptionSafeType[]>([])
    const [loading, setLoading] = useState(false)

    useEffect(() => {
        if (!disabled && currentTeamId) {
            setLoading(true)
            new ApiRequest()
                .pushSubscriptionsListSafe(currentTeamId)
                .get()
                .then((response: { results?: PushSubscriptionSafeType[] }) => {
                    let filtered = response.results || []
                    if (platform) {
                        filtered = filtered.filter((sub) => sub.platform === platform && sub.is_active)
                    } else {
                        filtered = filtered.filter((sub) => sub.is_active)
                    }
                    setSubscriptions(filtered)
                })
                .catch((error) => {
                    console.error('Failed to load push subscriptions', error)
                    setSubscriptions([])
                })
                .finally(() => {
                    setLoading(false)
                })
        }
    }, [currentTeamId, disabled, platform])

    const options: LemonInputSelectOption[] = useMemo(() => {
        return subscriptions.map((sub) => {
            const displayName = sub.person_name || sub.person_email || sub.distinct_id
            const displayLabel = `${displayName} (${sub.platform})`
            return {
                key: sub.id,
                labelComponent: (
                    <span className="flex items-center">
                        <span>{displayLabel}</span>
                    </span>
                ),
                label: displayLabel,
            }
        })
    }, [subscriptions])

    const selectedValue = useMemo(() => {
        if (!value) {
            return []
        }
        const sub = subscriptions.find((s) => s.id === value)
        return sub ? [value] : []
    }, [value, subscriptions])

    return (
        <LemonInputSelect
            onChange={(val) => onChange?.(val[0] ?? null)}
            value={selectedValue}
            disabled={disabled}
            mode="single"
            data-attr="select-push-subscription"
            placeholder="Select a push subscription..."
            options={options}
            loading={loading}
            emptyStateComponent={
                <p className="text-secondary italic p-1">
                    No push subscriptions found. Make sure devices have registered push notification tokens.
                </p>
            }
        />
    )
}

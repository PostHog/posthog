import { useValues } from 'kea'

import { LemonInputSelect, LemonInputSelectOption } from '@posthog/lemon-ui'

import { pushSubscriptionLogic } from './pushSubscriptionLogic'

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
    const logic = pushSubscriptionLogic({ platform })
    const { pushSubscriptionsLoading, options } = useValues(logic)

    const selectedValue = value ? [value] : []

    const optionsWithLabelComponents: LemonInputSelectOption[] = options.map((opt) => ({
        ...opt,
        labelComponent: (
            <span className="flex items-center">
                <span>{opt.label}</span>
            </span>
        ),
    }))

    return (
        <LemonInputSelect
            onChange={(val) => onChange?.(val[0] ?? null)}
            value={selectedValue}
            disabled={disabled}
            mode="single"
            data-attr="select-push-subscription"
            placeholder="Select a push subscription..."
            options={optionsWithLabelComponents}
            loading={pushSubscriptionsLoading}
            emptyStateComponent={
                !pushSubscriptionsLoading ? (
                    <p className="text-secondary italic p-1">
                        No push subscriptions found. Make sure devices have registered push notification tokens.
                    </p>
                ) : undefined
            }
        />
    )
}

import { ActivityChange, ChangeMapping } from 'lib/components/ActivityLog/humanizeActivity'
import { objectsEqual } from 'lib/utils/objects'

import { RevenueAnalyticsConfig, RevenueAnalyticsEventItem } from '~/queries/schema/schema-general'

export const revenueAnalyticsConfigurationDescriber = (change?: ActivityChange): ChangeMapping | null => {
    if (!change) {
        return null
    }

    const before = (change.before ?? {}) as RevenueAnalyticsConfig
    const after = (change.after ?? {}) as RevenueAnalyticsConfig

    const eventConfigDescriptions = revenueAnalyticsEventConfigDescriber(before, after) ?? []
    const filterTestAccountsConfigDescriptions = revenueAnalyticsFilterTestAccountsConfigDescriber(before, after) ?? []

    return {
        description: [...eventConfigDescriptions, ...filterTestAccountsConfigDescriptions],
    }
}

const revenueAnalyticsEventConfigDescriber = (
    before: RevenueAnalyticsConfig,
    after: RevenueAnalyticsConfig
): JSX.Element[] | null => {
    const diff: Record<string, { before?: RevenueAnalyticsEventItem; after?: RevenueAnalyticsEventItem }> = {}

    for (const event of before.events) {
        diff[event.eventName] ||= {}
        diff[event.eventName].before = event
    }

    for (const event of after.events) {
        diff[event.eventName] ||= {}
        diff[event.eventName].after = event
    }

    const descriptions = []
    for (const eventName in diff) {
        const { before, after } = diff[eventName]

        if (before && !after) {
            descriptions.push(
                <>
                    removed the Revenue analytics event <code>{eventName}</code>
                </>
            )
        } else if (!before && after) {
            descriptions.push(
                <>
                    added the Revenue analytics event <code>{eventName}</code>
                </>
            )
        } else if (before && after) {
            if (before.currencyAwareDecimal !== after.currencyAwareDecimal) {
                descriptions.push(
                    <>
                        {after.currencyAwareDecimal ? 'enabled' : 'disabled'} the Revenue analytics event{' '}
                        <code>{eventName}</code> currency aware configuration
                    </>
                )
            }

            if (before.revenueProperty !== after.revenueProperty) {
                descriptions.push(
                    <>
                        updated the Revenue analytics event <code>{eventName}</code> revenue property to{' '}
                        <code>{after.revenueProperty}</code>
                    </>
                )
            }

            if (!objectsEqual(before.revenueCurrencyProperty, after.revenueCurrencyProperty)) {
                const type = after.revenueCurrencyProperty.property ? 'event property' : 'static currency'
                const value = after.revenueCurrencyProperty.property ?? after.revenueCurrencyProperty.static
                descriptions.push(
                    <>
                        updated the Revenue analytics event <code>{eventName}</code> revenue currency property to {type}{' '}
                        <code>{value}</code>
                    </>
                )
            }
        }
    }

    return descriptions
}

const revenueAnalyticsFilterTestAccountsConfigDescriber = (
    before: RevenueAnalyticsConfig,
    after: RevenueAnalyticsConfig
): JSX.Element[] | null => {
    if (before.filter_test_accounts === after.filter_test_accounts) {
        return null
    }

    return [
        <>
            {after.filter_test_accounts ? 'enabled' : 'disabled'} the <em>filter out internal and test users</em>{' '}
            configuration for Revenue analytics
        </>,
    ]
}

import { Link, ProfilePicture } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { humanFriendlyCurrency, humanFriendlyLargeNumber, humanFriendlyNumber, percentage } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import type { LinkedAccountRoleApi, TicketLinkedAccountApi } from '../../generated/api.schemas'

const EMPTY_VALUE = '—'

// Format a custom property value for display per its definition's display type. The value arrives
// as its coerced JSON type (string / number / boolean / ISO date string), not always a string.
function formatCustomValue(value: unknown, displayType: string, isBigNumber: boolean): string {
    if (value === null || value === undefined || value === '') {
        return EMPTY_VALUE
    }
    const numeric = Number(value)
    const isNumber = Number.isFinite(numeric)
    switch (displayType) {
        case 'currency':
            return isNumber ? humanFriendlyCurrency(numeric) : String(value)
        // Percent values are stored as fractions (0.5 → 50%); percentage() multiplies by 100.
        case 'percent':
            return isNumber ? percentage(numeric) : String(value)
        case 'number':
            if (!isNumber) {
                return String(value)
            }
            return isBigNumber ? humanFriendlyLargeNumber(numeric) : humanFriendlyNumber(numeric)
        case 'boolean':
            return value ? 'Yes' : 'No'
        case 'date':
            return dayjs(String(value)).format('ll')
        case 'datetime':
            return dayjs(String(value)).format('lll')
        default:
            return String(value)
    }
}

function Row({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex items-start justify-between gap-2 py-1">
            <span className="text-muted shrink-0">{label}</span>
            <span className="text-right break-words min-w-0">{children}</span>
        </div>
    )
}

function RoleRow({ label, role }: { label: string; role: LinkedAccountRoleApi | null }): JSX.Element | null {
    if (!role) {
        return null
    }
    return (
        <Row label={label}>
            <span className="flex items-center gap-1 justify-end">
                <ProfilePicture user={{ email: role.email }} size="sm" />
                <span>{role.email}</span>
            </span>
        </Row>
    )
}

export function TicketAccountDetails({ account }: { account: TicketLinkedAccountApi }): JSX.Element {
    const externalIds: { label: string; value: string | null }[] = [
        { label: 'Stripe customer', value: account.stripe_customer_id },
        { label: 'HubSpot deal', value: account.hubspot_deal_id },
        { label: 'Billing ID', value: account.billing_id },
        { label: 'Salesforce ID', value: account.sfdc_id },
        { label: 'Zendesk ID', value: account.zendesk_id },
        { label: 'Slack channel', value: account.slack_channel_id },
    ]
    const setExternalIds = externalIds.filter((entry) => !!entry.value)

    return (
        <div className="text-sm">
            <Row label="Name">
                <Link to={urls.customerAnalyticsAccount(account.id)}>{account.name}</Link>
            </Row>
            <RoleRow label="CSM" role={account.csm} />
            <RoleRow label="Account executive" role={account.account_executive} />
            <RoleRow label="Account owner" role={account.account_owner} />
            {account.custom_properties.map((property) => (
                <Row key={property.name} label={property.name}>
                    {formatCustomValue(property.value, property.display_type, property.is_big_number)}
                </Row>
            ))}
            {setExternalIds.map((entry) => (
                <Row key={entry.label} label={entry.label}>
                    {entry.value}
                </Row>
            ))}
            {account.usage_dashboard_link && (
                <Row label="Usage dashboard">
                    <Link to={account.usage_dashboard_link} target="_blank">
                        View
                    </Link>
                </Row>
            )}
        </div>
    )
}

import type { LemonTagType } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import type { AccountApi } from 'products/customer_analytics/frontend/generated/api.schemas'

export interface AccountStatusTag {
    field: 'churned_at' | 'ignored_at'
    label: string
    type: LemonTagType
    dateLabel: string
    dataAttr: string
}

const STATUS_TAGS = [
    {
        field: 'churned_at',
        label: 'Churned',
        type: 'danger',
        datePrefix: 'Churned on',
        dataAttr: 'account-churned-tag',
    },
    {
        field: 'ignored_at',
        label: 'Ignored',
        type: 'warning',
        datePrefix: 'Ignored since',
        dataAttr: 'account-ignored-tag',
    },
] as const

export function getAccountStatusTags(account: Pick<AccountApi, 'churned_at' | 'ignored_at'>): AccountStatusTag[] {
    return STATUS_TAGS.flatMap(({ field, label, type, datePrefix, dataAttr }) => {
        const date = account[field]
        return date
            ? [{ field, label, type, dataAttr, dateLabel: `${datePrefix} ${dayjs(date).format('MMM D, YYYY')}` }]
            : []
    })
}

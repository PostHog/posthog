import { useActions } from 'kea'

import { LemonTag, LemonTagType, Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import type { AccountApi } from '../../generated/api.schemas'
import { customerAnalyticsAccountSceneLogic } from './customerAnalyticsAccountSceneLogic'

const STATUS_TAGS: {
    field: 'churned_at' | 'ignored_at'
    label: string
    type: LemonTagType
    tooltipPrefix: string
    dataAttr: string
}[] = [
    {
        field: 'churned_at',
        label: 'Churned',
        type: 'danger',
        tooltipPrefix: 'Churned on',
        dataAttr: 'account-churned-tag',
    },
    {
        field: 'ignored_at',
        label: 'Ignored',
        type: 'warning',
        tooltipPrefix: 'Ignored since',
        dataAttr: 'account-ignored-tag',
    },
]

function formatStatusDate(date: string): string {
    return dayjs(date).format('MMM D, YYYY')
}

export function AccountStatusTags({ account }: { account: AccountApi }): JSX.Element | null {
    const { openAccountEditor } = useActions(customerAnalyticsAccountSceneLogic)
    const visibleTags = STATUS_TAGS.flatMap((statusTag) => {
        const date = account[statusTag.field]
        return date ? [{ ...statusTag, date }] : []
    })

    if (visibleTags.length === 0) {
        return null
    }

    return (
        <div className="flex items-center gap-2">
            {visibleTags.map(({ field, label, type, tooltipPrefix, dataAttr, date }) => (
                <Tooltip key={field} title={`${tooltipPrefix} ${formatStatusDate(date)}`}>
                    <button type="button" className="inline-flex cursor-pointer" onClick={openAccountEditor}>
                        <LemonTag type={type} data-attr={dataAttr}>
                            {label}
                        </LemonTag>
                    </button>
                </Tooltip>
            ))}
        </div>
    )
}

import { useValues } from 'kea'

import { Link, ProfilePicture } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { fullName } from 'lib/utils/strings'
import { membersLogic } from 'scenes/organization/membersLogic'

import type {
    AccountApi,
    CustomPropertyDefinitionApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'
import { formatCustomPropertyValue } from 'products/customer_analytics/frontend/scenes/CustomerAnalyticsConfigurationScene/account/customPropertyTypes'

import { accountFieldValue, AccountPropertyDescriptor } from '../accountDetailProperties'
import type { CustomPropertyValue } from '../accountDetailPropertiesLogic'

const EMPTY = <span className="text-lg font-semibold text-muted">—</span>

function DateValue({ value, withTime }: { value: string; withTime: boolean }): JSX.Element {
    const parsed = dayjs(value)
    if (!parsed.isValid()) {
        return <span className="text-lg font-semibold">{value}</span>
    }
    return (
        <>
            <span className="text-lg font-semibold">
                {withTime ? (
                    <TZLabel time={parsed} formatDate="MMM D, YYYY" formatTime="HH:mm" />
                ) : (
                    parsed.format('MMM D, YYYY')
                )}
            </span>
            <span className="text-xs text-secondary">{parsed.fromNow()}</span>
        </>
    )
}

function CustomValue({
    definition,
    value,
}: {
    definition: CustomPropertyDefinitionApi
    value: CustomPropertyValue | undefined
}): JSX.Element {
    if (value === undefined || value === null || value === '') {
        return EMPTY
    }
    const raw = String(value)
    switch (definition.display_type) {
        case 'boolean':
            return <span className="text-lg font-semibold">{value === true || raw === 'true' ? 'Yes' : 'No'}</span>
        case 'link':
            return (
                <Link to={raw} target="_blank" className="text-lg font-semibold truncate">
                    {raw}
                </Link>
            )
        case 'date':
        case 'datetime':
            return <DateValue value={raw} withTime={definition.display_type === 'datetime'} />
        case 'percent': {
            const numeric = Number(raw)
            return (
                <>
                    <span className="text-lg font-semibold tabular-nums">
                        {formatCustomPropertyValue(raw, definition)}
                    </span>
                    {Number.isFinite(numeric) ? <LemonProgress percent={numeric * 100} className="mt-1" /> : null}
                </>
            )
        }
        default:
            return (
                <span className="text-lg font-semibold tabular-nums truncate">
                    {formatCustomPropertyValue(raw, definition)}
                </span>
            )
    }
}

function RelationshipValue({ userIds }: { userIds: number[] }): JSX.Element {
    const { meFirstMembers } = useValues(membersLogic)
    if (userIds.length === 0) {
        return <span className="text-sm text-muted">Unassigned</span>
    }
    return (
        <div className="flex flex-col gap-1">
            {userIds.map((userId) => {
                const user = meFirstMembers.find((member) => member.user.id === userId)?.user ?? null
                return (
                    <span key={userId} className="inline-flex items-center gap-2 min-w-0">
                        {user ? <ProfilePicture user={user} size="sm" /> : null}
                        <span className="text-sm font-medium truncate">
                            {user ? fullName(user) || user.email : 'Unknown user'}
                        </span>
                    </span>
                )
            })}
        </div>
    )
}

function FieldValue({
    descriptor,
    account,
}: {
    descriptor: AccountPropertyDescriptor & { kind: 'field' }
    account: AccountApi
}): JSX.Element {
    const value = accountFieldValue(account, descriptor.field)
    if (!value) {
        return EMPTY
    }
    if (descriptor.field === 'website_domain') {
        return (
            <Link to={`https://${value}`} target="_blank" className="text-lg font-semibold truncate">
                {value}
            </Link>
        )
    }
    return <DateValue value={value} withTime={false} />
}

export interface AccountPropertyValueProps {
    descriptor: AccountPropertyDescriptor
    account: AccountApi
    customValue: CustomPropertyValue | undefined
    relationshipUserIds: number[]
}

export function AccountPropertyValue({
    descriptor,
    account,
    customValue,
    relationshipUserIds,
}: AccountPropertyValueProps): JSX.Element {
    if (descriptor.kind === 'custom') {
        return <CustomValue definition={descriptor.definition} value={customValue} />
    }
    if (descriptor.kind === 'relationship') {
        return <RelationshipValue userIds={relationshipUserIds} />
    }
    return <FieldValue descriptor={descriptor} account={account} />
}

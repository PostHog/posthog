import { useActions, useValues } from 'kea'

import { LemonBanner, Spinner } from '@posthog/lemon-ui'

import type { BookActivityMatrixResult } from '~/queries/schema/schema-general'

import { AccountProductUsagePeople } from './AccountProductUsagePeople'
import { getLatestProductUsageColumn, getAccountProductUsagePeopleCell } from './accountProductUsagePeople'
import { accountProductUsagePeopleLogic } from './accountProductUsagePeopleLogic'
import { AccountProductUsageTable } from './AccountProductUsageTable'

export function AccountProductUsage({
    result,
    accountId,
    instanceId,
    includeFirstUse,
    onIncludeFirstUseChange,
    loading,
}: {
    result: BookActivityMatrixResult
    accountId: string
    instanceId: string
    includeFirstUse: boolean
    onIncludeFirstUseChange: (value: boolean) => void
    loading?: boolean
}): JSX.Element {
    const logic = accountProductUsagePeopleLogic({ result, accountId, instanceId, includeFirstUse })
    const { details, detailsLoading, error } = useValues(logic)
    const { loadDetails } = useActions(logic)
    const latestColumn = getLatestProductUsageColumn(result)
    const renderPeople = (productKey: string, columnKey: string): JSX.Element | null => {
        if (detailsLoading) {
            return <Spinner className="text-xl" />
        }
        if (!details) {
            return null
        }
        const { people, total } = getAccountProductUsagePeopleCell(
            result,
            accountId,
            details.people.people,
            productKey,
            columnKey
        )
        return (
            <AccountProductUsagePeople
                people={people}
                firsts={includeFirstUse ? (details.firsts?.people ?? []) : []}
                total={total}
                columnKey={columnKey}
            />
        )
    }
    return (
        <div className="flex flex-col gap-2 min-w-0">
            {error && (
                <LemonBanner
                    type="error"
                    action={{
                        children: 'Try again',
                        onClick: () => loadDetails(),
                        'data-attr': 'account-product-usage-people-retry',
                    }}
                >
                    Could not load user details. Try again.
                </LemonBanner>
            )}
            {(details?.people.truncated || details?.firsts?.truncated) && (
                <LemonBanner type="warning">
                    Some user details are missing because the result reached its limit.
                </LemonBanner>
            )}
            <AccountProductUsageTable
                result={result}
                accountId={accountId}
                instanceId={instanceId}
                includeFirstUse={includeFirstUse}
                onIncludeFirstUseChange={onIncludeFirstUseChange}
                loading={loading}
                renderTopUsers={(productKey) => renderPeople(productKey, latestColumn)}
                renderUserDetails={renderPeople}
            />
        </div>
    )
}

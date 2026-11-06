import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonBanner, LemonModal, Spinner } from '@posthog/lemon-ui'

import type { BookActivityMatrixResult } from '~/queries/schema/schema-general'

import { AccountProductUsagePeople } from './AccountProductUsagePeople'
import { getLatestProductUsageColumn, getAccountProductUsagePeopleCell } from './accountProductUsagePeopleData'
import { accountProductUsagePeopleLogic } from './accountProductUsagePeopleLogic'
import { AccountProductUsageQualifications } from './AccountProductUsageQualifications'
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
    const [inspectedCell, setInspectedCell] = useState<{
        matrix: BookActivityMatrixResult
        productKey: string
        columnKey: string
    } | null>(null)
    const inspected =
        !error && inspectedCell?.matrix === result && details?.matrix === result
            ? getAccountProductUsagePeopleCell(
                  result,
                  accountId,
                  details.people.people,
                  inspectedCell.productKey,
                  inspectedCell.columnKey
              )
            : null
    const latestColumn = getLatestProductUsageColumn(result)
    const renderPeople = (productKey: string, columnKey: string, showDetails = false): JSX.Element | null => {
        if (detailsLoading && details?.matrix !== result) {
            return <Spinner className="text-xl" />
        }
        if (error || !details || details.matrix !== result) {
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
                people={showDetails ? people : people.slice(0, 3)}
                productLabel={result.series.find((product) => product.key === productKey)?.label ?? productKey}
                partial={result.columns.find((column) => column.key === columnKey)?.partial}
                total={total}
                columnKey={columnKey}
                showDetails={showDetails}
                disableTooltip={!!inspected}
                onInspect={() => setInspectedCell({ matrix: result, productKey, columnKey })}
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
            {inspected && inspectedCell && (
                <LemonModal isOpen title="Qualification details" onClose={() => setInspectedCell(null)} width={560}>
                    <div className="flex flex-col gap-4">
                        <AccountProductUsagePeople
                            people={inspected.people}
                            total={inspected.total}
                            columnKey={inspectedCell.columnKey}
                            productLabel={
                                result.series.find((product) => product.key === inspectedCell.productKey)?.label ??
                                inspectedCell.productKey
                            }
                            partial={result.columns.find((column) => column.key === inspectedCell.columnKey)?.partial}
                            showDetails
                        />
                        <AccountProductUsageQualifications
                            people={inspected.people}
                            firsts={includeFirstUse ? (details?.firsts?.people ?? []) : []}
                            columnKey={inspectedCell.columnKey}
                        />
                    </div>
                </LemonModal>
            )}
            <AccountProductUsageTable
                result={result}
                accountId={accountId}
                instanceId={instanceId}
                includeFirstUse={includeFirstUse}
                firstUse={
                    includeFirstUse && !error && details?.matrix === result ? (details.firsts?.accounts ?? []) : []
                }
                onIncludeFirstUseChange={onIncludeFirstUseChange}
                loading={loading}
                renderTopUsers={(productKey) => renderPeople(productKey, latestColumn)}
                renderUserDetails={
                    inspected ? undefined : (productKey, columnKey) => renderPeople(productKey, columnKey, true)
                }
            />
        </div>
    )
}

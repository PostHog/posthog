import { useActions, useValues } from 'kea'

import { Button } from '@posthog/quill'

import { pluralize } from 'lib/utils/strings'

import { dataQualityOverviewLogic } from 'products/data_quality/frontend/overview/dataQualityOverviewLogic'

import { canCertify } from '../catalogTableRows'
import { TablesBulkAction, catalogTablesLogic } from '../catalogTablesLogic'
import { CatalogBulkBar } from '../components/CatalogBulkBar'
import { CatalogReviewAccess } from './CatalogReviewAccess'

function disabledReasonFor(
    count: number,
    emptyReason: string,
    bulkActionInFlight: TablesBulkAction | null,
    action: TablesBulkAction
): string | undefined {
    if (count === 0) {
        return emptyReason
    }
    return bulkActionInFlight && bulkActionInFlight !== action ? 'Another bulk action is running' : undefined
}

export function CatalogTablesBulkBar(): JSX.Element {
    const { selectedRows, selectedProposalRows, bulkActionInFlight } = useValues(catalogTablesLogic)
    const { reviewProposals, certifyRows, runSelectedChecks, clearSelection } = useActions(catalogTablesLogic)
    const { startingRun, isRunning } = useValues(dataQualityOverviewLogic)
    const proposalKeys = selectedProposalRows.map((row) => row.key)
    const certifiableKeys = selectedRows.filter(canCertify).map((row) => row.key)
    const withChecks = selectedRows.filter((row) => row.checkGroup).length

    return (
        <CatalogBulkBar
            selectedLabel={`${pluralize(selectedRows.length, 'table')} selected`}
            onClear={clearSelection}
            dataAttr="data-catalog-tables-bulk-bar"
        >
            <CatalogReviewAccess>
                <Button
                    variant="outline"
                    size="sm"
                    loading={bulkActionInFlight === 'accept'}
                    disabledReason={disabledReasonFor(
                        proposalKeys.length,
                        'No selected table has a pending proposal',
                        bulkActionInFlight,
                        'accept'
                    )}
                    onClick={() => reviewProposals(proposalKeys, 'accept', 'bulk')}
                    data-attr="data-catalog-tables-bulk-accept"
                >
                    Accept {pluralize(proposalKeys.length, 'proposal')}
                </Button>
            </CatalogReviewAccess>
            <CatalogReviewAccess>
                <Button
                    variant="outline"
                    size="sm"
                    loading={bulkActionInFlight === 'reject'}
                    disabledReason={disabledReasonFor(
                        proposalKeys.length,
                        'No selected table has a pending proposal',
                        bulkActionInFlight,
                        'reject'
                    )}
                    onClick={() => reviewProposals(proposalKeys, 'reject', 'bulk')}
                    data-attr="data-catalog-tables-bulk-reject"
                >
                    Reject
                </Button>
            </CatalogReviewAccess>
            <Button
                variant="outline"
                size="sm"
                disabledReason={
                    withChecks === 0
                        ? 'No selected table has checks'
                        : startingRun || isRunning
                          ? 'Checks are already running'
                          : undefined
                }
                onClick={runSelectedChecks}
                data-attr="data-catalog-tables-bulk-run-checks"
            >
                Run checks
            </Button>
            <CatalogReviewAccess>
                <Button
                    variant="outline"
                    size="sm"
                    loading={bulkActionInFlight === 'certify'}
                    disabledReason={disabledReasonFor(
                        certifiableKeys.length,
                        'Every selected table is already certified or cannot be certified',
                        bulkActionInFlight,
                        'certify'
                    )}
                    onClick={() => certifyRows(certifiableKeys, 'bulk')}
                    data-attr="data-catalog-tables-bulk-certify"
                >
                    Certify
                </Button>
            </CatalogReviewAccess>
        </CatalogBulkBar>
    )
}

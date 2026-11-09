import { useActions, useValues } from 'kea'

import { IconEllipsis } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { navigateToHref } from 'lib/utils/navigateToHref'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { modelsOverviewLogic } from 'products/data_modeling/frontend/modelsOverviewLogic'
import { REFRESHING_LABEL, REFRESH_LABEL } from 'products/data_modeling/frontend/overviewIssueCopy'
import { deleteDisabledReason, viewsTabLogic } from 'products/data_modeling/frontend/viewsTabLogic'
import { dataQualityCheckEditorLogic } from 'products/data_quality/frontend/dataQualityCheckEditorLogic'
import { dataQualityOverviewLogic } from 'products/data_quality/frontend/overview/dataQualityOverviewLogic'

import { CatalogTableRow, hasPendingProposal } from '../catalogTableRows'
import { catalogTablesLogic } from '../catalogTablesLogic'
import { certificationsLogic } from '../certificationsLogic'
import { confirmRevokeCertification } from '../confirmRevokeCertification'
import { CatalogReviewAccess } from './CatalogReviewAccess'

const CHECKS_RUNNING_REASON = 'Checks are already running'
const REFRESH_RUNNING_REASON = 'This view is already refreshing'
const RUNNING_STATUS = 'Running'
const CERTIFICATION_WORKING_REASON = 'Saving the last change'

const REMOVE_LABELS: Record<string, string> = {
    certified: 'Remove certification',
    deprecated: 'Remove deprecation',
}

function RefreshItem({
    savedQueryId,
    refreshing,
    dataAttr,
}: {
    savedQueryId: string
    refreshing: boolean
    dataAttr: string
}): JSX.Element {
    const { requestRefresh } = useActions(modelsOverviewLogic)
    return (
        <AccessControlAction
            resourceType={AccessControlResourceType.WarehouseObjects}
            minAccessLevel={AccessControlLevel.Editor}
        >
            <DropdownMenuItem
                onClick={() => requestRefresh(savedQueryId)}
                disabledReason={refreshing ? REFRESH_RUNNING_REASON : undefined}
                data-attr={dataAttr}
            >
                {refreshing ? REFRESHING_LABEL : REFRESH_LABEL}
            </DropdownMenuItem>
        </AccessControlAction>
    )
}

function NextStepItem({ row }: { row: CatalogTableRow }): JSX.Element | null {
    const nextStep = row.problems.length > 0 ? row.attention.nextStep : null
    if (!nextStep) {
        return null
    }
    if (nextStep.kind === 'refresh') {
        return (
            <RefreshItem
                savedQueryId={nextStep.savedQueryId}
                refreshing={nextStep.refreshing}
                dataAttr="data-catalog-tables-next-step"
            />
        )
    }
    return (
        <DropdownMenuItem onClick={() => navigateToHref(nextStep.href)} data-attr="data-catalog-tables-next-step">
            {nextStep.label}
        </DropdownMenuItem>
    )
}

function ChecksItem({ row }: { row: CatalogTableRow }): JSX.Element | null {
    const { startingRun, isRunning } = useValues(dataQualityOverviewLogic)
    const { setLastActionCheck } = useActions(dataQualityOverviewLogic)
    const { openEditor } = useActions(dataQualityCheckEditorLogic)
    const { runTableChecks } = useActions(catalogTablesLogic)
    if (row.checkGroup) {
        return (
            <DropdownMenuItem
                onClick={() => runTableChecks(row)}
                disabledReason={startingRun || isRunning ? CHECKS_RUNNING_REASON : undefined}
                data-attr="data-catalog-tables-run-checks"
            >
                Run checks
            </DropdownMenuItem>
        )
    }
    const subject = row.subject
    if (!subject) {
        return null
    }
    return (
        <DropdownMenuItem
            onClick={() => {
                setLastActionCheck(null)
                openEditor(null, subject)
            }}
            data-attr="data-catalog-tables-add-check"
        >
            Add check
        </DropdownMenuItem>
    )
}

function RefreshViewItem({ row }: { row: CatalogTableRow }): JSX.Element | null {
    const { refreshRequests } = useValues(modelsOverviewLogic)
    const savedQuery = row.savedQuery
    if (!savedQuery?.is_materialized || row.problems.length > 0) {
        return null
    }
    return (
        <RefreshItem
            savedQueryId={savedQuery.id}
            refreshing={savedQuery.status === RUNNING_STATUS || savedQuery.id in refreshRequests}
            dataAttr="data-catalog-tables-sync-now"
        />
    )
}

function TrustItems({ row }: { row: CatalogTableRow }): JSX.Element | null {
    const { actionsInFlight } = useValues(certificationsLogic)
    const { reviewingRows } = useValues(catalogTablesLogic)
    const { deprecateCertification } = useActions(certificationsLogic)
    const { reviewProposals, certifyRows } = useActions(catalogTablesLogic)
    const certification = row.certification
    if (!row.certificationTarget) {
        return null
    }
    const working =
        reviewingRows[row.key] || (certification && actionsInFlight[certification.id])
            ? CERTIFICATION_WORKING_REASON
            : undefined
    if (hasPendingProposal(row)) {
        return (
            <>
                <CatalogReviewAccess>
                    <DropdownMenuItem
                        onClick={() => reviewProposals([row.key], 'accept', 'menu')}
                        disabledReason={working}
                        data-attr="data-catalog-tables-accept-proposal"
                    >
                        Accept proposal
                    </DropdownMenuItem>
                </CatalogReviewAccess>
                <CatalogReviewAccess>
                    <DropdownMenuItem
                        onClick={() => reviewProposals([row.key], 'reject', 'menu')}
                        disabledReason={working}
                        data-attr="data-catalog-tables-reject-proposal"
                    >
                        Reject proposal
                    </DropdownMenuItem>
                </CatalogReviewAccess>
            </>
        )
    }
    if (certification?.status === 'certified') {
        return (
            <CatalogReviewAccess>
                <DropdownMenuItem
                    onClick={() => deprecateCertification(certification.id)}
                    disabledReason={working}
                    data-attr="data-catalog-tables-deprecate"
                >
                    Deprecate
                </DropdownMenuItem>
            </CatalogReviewAccess>
        )
    }
    return (
        <CatalogReviewAccess>
            <DropdownMenuItem
                onClick={() => certifyRows([row.key], 'menu')}
                disabledReason={working}
                data-attr="data-catalog-tables-certify"
            >
                Certify
            </DropdownMenuItem>
        </CatalogReviewAccess>
    )
}

function AccessControlItem({ row }: { row: CatalogTableRow }): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { openAccessControlModal } = useActions(viewsTabLogic)
    const savedQuery = row.savedQuery
    if (
        !savedQuery ||
        savedQuery.managed_viewset_kind !== null ||
        !featureFlags[FEATURE_FLAGS.HOGQL_WAREHOUSE_ACCESS_CONTROL]
    ) {
        return null
    }
    return (
        <DropdownMenuItem
            onClick={() => openAccessControlModal(savedQuery)}
            data-attr="data-catalog-tables-access-control"
        >
            Access control
        </DropdownMenuItem>
    )
}

function DestructiveItems({ row }: { row: CatalogTableRow }): JSX.Element | null {
    const { actionsInFlight } = useValues(certificationsLogic)
    const { revokeCertification } = useActions(certificationsLogic)
    const { deleteView } = useActions(viewsTabLogic)
    const { certification, savedQuery } = row
    const settledCertification = certification && !hasPendingProposal(row) ? certification : null
    if (!settledCertification && !savedQuery) {
        return null
    }
    return (
        <>
            <DropdownMenuSeparator />
            {settledCertification && (
                <CatalogReviewAccess>
                    <DropdownMenuItem
                        variant="destructive"
                        onClick={() =>
                            confirmRevokeCertification(settledCertification, () =>
                                revokeCertification(settledCertification.id)
                            )
                        }
                        disabledReason={
                            actionsInFlight[settledCertification.id] ? CERTIFICATION_WORKING_REASON : undefined
                        }
                        data-attr="data-catalog-tables-revoke"
                    >
                        {REMOVE_LABELS[settledCertification.status] ?? 'Remove certification'}
                    </DropdownMenuItem>
                </CatalogReviewAccess>
            )}
            {savedQuery && (
                <AccessControlAction
                    resourceType={AccessControlResourceType.WarehouseObjects}
                    minAccessLevel={AccessControlLevel.Editor}
                    userAccessLevel={savedQuery.user_access_level}
                >
                    <DropdownMenuItem
                        variant="destructive"
                        onClick={() => deleteView(savedQuery.id)}
                        disabledReason={deleteDisabledReason(savedQuery)}
                        data-attr="data-catalog-tables-delete"
                    >
                        Delete
                    </DropdownMenuItem>
                </AccessControlAction>
            )}
        </>
    )
}

export function CatalogTableRowMenu({ row }: { row: CatalogTableRow }): JSX.Element {
    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button
                        size="icon"
                        aria-label={`More actions for ${row.name}`}
                        className="text-muted-foreground"
                        data-attr="data-catalog-tables-row-actions"
                    />
                }
            >
                <IconEllipsis />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="min-w-48">
                <NextStepItem row={row} />
                <ChecksItem row={row} />
                <RefreshViewItem row={row} />
                <TrustItems row={row} />
                <AccessControlItem row={row} />
                <DestructiveItems row={row} />
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

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

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { modelsOverviewLogic } from 'products/data_modeling/frontend/modelsOverviewLogic'
import { subjectNextStep } from 'products/data_modeling/frontend/subjectNextStep'
import { deleteDisabledReason, viewsTabLogic } from 'products/data_modeling/frontend/viewsTabLogic'
import { dataQualityCheckEditorLogic } from 'products/data_quality/frontend/dataQualityCheckEditorLogic'
import { dataQualityOverviewLogic } from 'products/data_quality/frontend/overview/dataQualityOverviewLogic'

import { CatalogTableRow } from '../catalogTableRows'
import { catalogTablesLogic } from '../catalogTablesLogic'
import { certificationsLogic } from '../certificationsLogic'
import { confirmRevokeCertification } from '../confirmRevokeCertification'

const CHECKS_RUNNING_REASON = 'Checks are already running'
const SYNC_RUNNING_REASON = 'Materialization is already running'
const CERTIFICATION_WORKING_REASON = 'Saving the last change'

function NextStepItem({ row }: { row: CatalogTableRow }): JSX.Element | null {
    const { startedRefreshSavedQueryIds } = useValues(modelsOverviewLogic)
    const { runDataWarehouseSavedQuery } = useActions(modelsOverviewLogic)
    const nextStep = row.problems.length > 0 ? subjectNextStep(row.health) : null
    if (!nextStep) {
        return null
    }
    if (nextStep.kind === 'link') {
        return (
            <DropdownMenuItem
                onClick={() => router.actions.push(nextStep.href)}
                data-attr="data-catalog-tables-next-step"
            >
                {nextStep.label}
            </DropdownMenuItem>
        )
    }
    return (
        <AccessControlAction
            resourceType={AccessControlResourceType.WarehouseObjects}
            minAccessLevel={AccessControlLevel.Editor}
        >
            <DropdownMenuItem
                onClick={() => runDataWarehouseSavedQuery(nextStep.savedQueryId)}
                disabledReason={
                    startedRefreshSavedQueryIds.includes(nextStep.savedQueryId) ? 'Refresh started' : undefined
                }
                data-attr="data-catalog-tables-next-step"
            >
                {nextStep.label}
            </DropdownMenuItem>
        </AccessControlAction>
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

function SyncNowItem({ row }: { row: CatalogTableRow }): JSX.Element | null {
    const { runMaterialization } = useActions(viewsTabLogic)
    const savedQuery = row.savedQuery
    if (!savedQuery?.is_materialized || row.problems.length > 0) {
        return null
    }
    return (
        <AccessControlAction
            resourceType={AccessControlResourceType.WarehouseObjects}
            minAccessLevel={AccessControlLevel.Editor}
        >
            <DropdownMenuItem
                onClick={() => runMaterialization(savedQuery.id)}
                disabledReason={savedQuery.status === 'Running' ? SYNC_RUNNING_REASON : undefined}
                data-attr="data-catalog-tables-sync-now"
            >
                Sync now
            </DropdownMenuItem>
        </AccessControlAction>
    )
}

function TrustItems({ row }: { row: CatalogTableRow }): JSX.Element | null {
    const { actionsInFlight } = useValues(certificationsLogic)
    const { certifyCertification, deprecateCertification } = useActions(certificationsLogic)
    const { proposeCertification } = useActions(catalogTablesLogic)
    const certification = row.certification
    if (!row.certificationTarget) {
        return null
    }
    if (!certification) {
        return (
            <DropdownMenuItem
                onClick={() => proposeCertification(row)}
                data-attr="data-catalog-tables-propose-certification"
            >
                Propose certification
            </DropdownMenuItem>
        )
    }
    const working = actionsInFlight[certification.id] ? CERTIFICATION_WORKING_REASON : undefined
    return (
        <>
            {certification.status !== 'certified' && (
                <DropdownMenuItem
                    onClick={() => certifyCertification(certification.id)}
                    disabledReason={working}
                    data-attr="data-catalog-tables-certify"
                >
                    Certify
                </DropdownMenuItem>
            )}
            {certification.status !== 'deprecated' && (
                <DropdownMenuItem
                    onClick={() => deprecateCertification(certification.id)}
                    disabledReason={working}
                    data-attr="data-catalog-tables-deprecate"
                >
                    Deprecate
                </DropdownMenuItem>
            )}
        </>
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
    if (!certification && !savedQuery) {
        return null
    }
    return (
        <>
            <DropdownMenuSeparator />
            {certification && (
                <DropdownMenuItem
                    variant="destructive"
                    onClick={() =>
                        confirmRevokeCertification(certification, () => revokeCertification(certification.id))
                    }
                    disabledReason={actionsInFlight[certification.id] ? CERTIFICATION_WORKING_REASON : undefined}
                    data-attr="data-catalog-tables-revoke"
                >
                    Revoke certification
                </DropdownMenuItem>
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
                <SyncNowItem row={row} />
                <TrustItems row={row} />
                <AccessControlItem row={row} />
                <DestructiveItems row={row} />
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

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

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { modelsOverviewLogic } from 'products/data_modeling/frontend/modelsOverviewLogic'

import { CatalogTableRow, RowMenuAction, rowMenuActions } from '../catalogTableRows'
import { catalogTablesLogic } from '../catalogTablesLogic'
import { certificationsLogic } from '../certificationsLogic'
import { confirmRevokeCertification } from '../confirmRevokeCertification'
import { CatalogReviewAccess } from './CatalogReviewAccess'

const SYNC_RUNNING_REASON = 'This view is already refreshing'
const CERTIFICATION_WORKING_REASON = 'Saving the last change'

const REMOVE_LABELS: Record<string, string> = {
    certified: 'Remove certification',
    deprecated: 'Remove deprecation',
}

function SyncNowItem({ row }: { row: CatalogTableRow }): JSX.Element | null {
    const { requestRefresh } = useActions(modelsOverviewLogic)
    const savedQuery = row.savedQuery
    if (!savedQuery) {
        return null
    }
    return (
        <AccessControlAction
            resourceType={AccessControlResourceType.WarehouseObjects}
            minAccessLevel={AccessControlLevel.Editor}
        >
            <DropdownMenuItem
                onClick={() => requestRefresh(savedQuery.id)}
                disabledReason={row.refreshing ? SYNC_RUNNING_REASON : undefined}
                data-attr="data-catalog-tables-sync-now"
            >
                Sync now
            </DropdownMenuItem>
        </AccessControlAction>
    )
}

function TrustItems({ row, menuActions }: { row: CatalogTableRow; menuActions: RowMenuAction[] }): JSX.Element {
    const { actionsInFlight } = useValues(certificationsLogic)
    const { deprecateCertification, revokeCertification } = useActions(certificationsLogic)
    const { certifyRows } = useActions(catalogTablesLogic)
    const { certification } = row
    const working = certification && actionsInFlight[certification.id] ? CERTIFICATION_WORKING_REASON : undefined
    return (
        <>
            <CatalogReviewAccess>
                {certification && menuActions.includes('deprecate') ? (
                    <DropdownMenuItem
                        onClick={() => deprecateCertification(certification.id)}
                        disabledReason={working}
                        data-attr="data-catalog-tables-deprecate"
                    >
                        Deprecate
                    </DropdownMenuItem>
                ) : (
                    <DropdownMenuItem
                        onClick={() => certifyRows([row.key], 'inline')}
                        disabledReason={working}
                        data-attr="data-catalog-tables-certify"
                    >
                        Certify
                    </DropdownMenuItem>
                )}
            </CatalogReviewAccess>
            {certification && menuActions.includes('remove_trust') && (
                <>
                    <DropdownMenuSeparator />
                    <CatalogReviewAccess>
                        <DropdownMenuItem
                            variant="destructive"
                            onClick={() =>
                                confirmRevokeCertification(certification, () => revokeCertification(certification.id))
                            }
                            disabledReason={working}
                            data-attr="data-catalog-tables-revoke"
                        >
                            {REMOVE_LABELS[certification.status] ?? 'Remove certification'}
                        </DropdownMenuItem>
                    </CatalogReviewAccess>
                </>
            )}
        </>
    )
}

export function CatalogTableRowMenu({ row }: { row: CatalogTableRow }): JSX.Element | null {
    const { certificationsLoadFailed } = useValues(catalogTablesLogic)
    const menuActions = rowMenuActions(row, !certificationsLoadFailed)
    if (menuActions.length === 0) {
        return null
    }
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
                {menuActions.includes('sync_now') && <SyncNowItem row={row} />}
                {(menuActions.includes('certify') || menuActions.includes('deprecate')) && (
                    <TrustItems row={row} menuActions={menuActions} />
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

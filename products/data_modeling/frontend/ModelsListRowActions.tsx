import { useActions, useValues } from 'kea'

import { IconEllipsis } from '@posthog/icons'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { FEATURE_FLAGS } from 'lib/constants'
import type { DataWarehouseSavedQuerySummary } from 'scenes/data-warehouse/saved_queries/dataWarehouseViewsLogic'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { deleteDisabledReason, viewsTabLogic } from './viewsTabLogic'

const RUNNING_REASON = 'Materialization is already running'

export function ModelsListRowActions({ view }: { view: DataWarehouseSavedQuerySummary }): JSX.Element {
    const { featureFlags } = useValues(viewsTabLogic)
    const { runMaterialization, openAccessControlModal, deleteView } = useActions(viewsTabLogic)
    const showAccessControl =
        !!featureFlags[FEATURE_FLAGS.HOGQL_WAREHOUSE_ACCESS_CONTROL] && view.managed_viewset_kind === null

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button
                        variant="default"
                        size="icon"
                        aria-label={`More actions for ${view.name}`}
                        data-attr="models-list-row-actions"
                    />
                }
            >
                <IconEllipsis />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
                {view.is_materialized && (
                    <AccessControlAction
                        resourceType={AccessControlResourceType.WarehouseObjects}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <DropdownMenuItem
                            onClick={() => runMaterialization(view.id)}
                            disabledReason={view.status === 'Running' ? RUNNING_REASON : undefined}
                            data-attr="models-list-sync-now"
                        >
                            Sync now
                        </DropdownMenuItem>
                    </AccessControlAction>
                )}
                {showAccessControl && (
                    <DropdownMenuItem
                        onClick={() => openAccessControlModal(view)}
                        data-attr="models-list-access-control"
                    >
                        Access control
                    </DropdownMenuItem>
                )}
                <AccessControlAction
                    resourceType={AccessControlResourceType.WarehouseObjects}
                    minAccessLevel={AccessControlLevel.Editor}
                    userAccessLevel={view.user_access_level}
                >
                    <DropdownMenuItem
                        variant="destructive"
                        onClick={() => deleteView(view.id)}
                        disabledReason={deleteDisabledReason(view)}
                        data-attr="models-list-delete"
                    >
                        Delete
                    </DropdownMenuItem>
                </AccessControlAction>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

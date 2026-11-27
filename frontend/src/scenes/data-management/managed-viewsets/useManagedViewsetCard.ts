import { useActions, useValues } from 'kea'

import { teamLogic } from 'scenes/teamLogic'

import { DataWarehouseManagedViewsetKind } from '~/queries/schema/schema-general'

import {
    DataWarehouseManagedViewsetsLogicProps,
    dataWarehouseManagedViewsetsLogic,
} from './dataWarehouseManagedViewsetsLogic'

export interface ManagedViewsetCardState {
    isEnabled: boolean
    isToggling: boolean
    toggleViewset: (kind: DataWarehouseManagedViewsetKind, enabled: boolean) => void
}

/** The toggle state both viewset cards show, read from the team and the viewsets logic. */
export function useManagedViewsetCard(
    type: DataWarehouseManagedViewsetsLogicProps['type'],
    kind: DataWarehouseManagedViewsetKind
): ManagedViewsetCardState {
    const { currentTeam } = useValues(teamLogic)
    const { toggleViewset } = useActions(dataWarehouseManagedViewsetsLogic({ type }))
    const { togglingViewset, toggleResultLoading } = useValues(dataWarehouseManagedViewsetsLogic({ type }))

    return {
        isEnabled: !!currentTeam?.managed_viewsets?.[kind],
        isToggling: togglingViewset === kind && toggleResultLoading,
        toggleViewset,
    }
}

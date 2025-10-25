import { actions, connect, kea, key, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import { DataWarehouseManagedViewsetKind } from '~/queries/schema/schema-general'

import type { dataWarehouseManagedViewsetsLogicType } from './dataWarehouseManagedViewsetsLogicType'
import {
    DisableDataWarehouseManagedViewsetModalLogicProps,
    disableDataWarehouseManagedViewsetModalLogic,
} from './disableDataWarehouseManagedViewsetModalLogic'

export interface DataWarehouseManagedViewsetsLogicProps {
    type: DisableDataWarehouseManagedViewsetModalLogicProps['type']
}

export const dataWarehouseManagedViewsetsLogic = kea<dataWarehouseManagedViewsetsLogicType>([
    props({ type: 'root' } as DataWarehouseManagedViewsetsLogicProps),
    key(({ type }) => `dataWarehouseManagedViewsetsLogic-${type}`),
    path((key) => ['scenes', 'data-management', 'managed-viewsets', key]),
    connect((props: DataWarehouseManagedViewsetsLogicProps) => ({
        values: [teamLogic, ['currentTeam']],
        actions: [
            teamLogic,
            ['loadCurrentTeam'],
            disableDataWarehouseManagedViewsetModalLogic({ type: props.type }),
            ['openModal'],
        ],
    })),
    actions({
        toggleViewset: (kind: DataWarehouseManagedViewsetKind, enabled: boolean) => ({ kind, enabled }),
    }),
    reducers({
        togglingViewset: [
            null as DataWarehouseManagedViewsetKind | null,
            {
                toggleViewset: (_, { kind }) => kind,
            },
        ],
    }),
    loaders(({ actions }) => ({
        toggleResult: [
            null as void | null,
            {
                toggleViewset: async ({ kind, enabled }) => {
                    // If disabling, show confirmation modal instead
                    if (!enabled) {
                        actions.openModal(kind)
                        return
                    }

                    // If enabling, proceed directly
                    try {
                        await api.dataWarehouseManagedViewsets.toggle(kind, true)
                        lemonToast.success(`Viewset enabled successfully`)
                        actions.loadCurrentTeam()
                    } catch (error: any) {
                        lemonToast.error(`Failed to enable viewset: ${error.message || 'Unknown error'}`)
                        throw error
                    }
                },
            },
        ],
    })),
])

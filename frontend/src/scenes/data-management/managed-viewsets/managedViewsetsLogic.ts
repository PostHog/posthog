import { actions, connect, kea, key, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import { ManagedViewsetKind } from '~/queries/schema/schema-general'

import {
    DisableManagedViewsetModalLogicProps,
    disableManagedViewsetModalLogic,
} from './disableManagedViewsetModalLogic'
import type { managedViewsetsLogicType } from './managedViewsetsLogicType'

export interface ManagedViewsetsLogicProps {
    type: DisableManagedViewsetModalLogicProps['type']
}

export const managedViewsetsLogic = kea<managedViewsetsLogicType>([
    props({ type: 'root' } as ManagedViewsetsLogicProps),
    key(({ type }) => `managedViewsetsLogic-${type}`),
    path((key) => ['scenes', 'data-management', 'managed-viewsets', key]),
    connect((props: ManagedViewsetsLogicProps) => ({
        values: [teamLogic, ['currentTeam']],
        actions: [teamLogic, ['loadCurrentTeam'], disableManagedViewsetModalLogic({ type: props.type }), ['openModal']],
    })),
    actions({
        toggleViewset: (kind: ManagedViewsetKind, enabled: boolean) => ({ kind, enabled }),
    }),
    reducers({
        togglingViewset: [
            null as ManagedViewsetKind | null,
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
                        await api.managedViewsets.toggle(kind, true)
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

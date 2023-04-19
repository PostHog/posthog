import { actions, kea, path, reducers } from 'kea'
import { BatchExportDestinationType, CDPTabsType, ConnectionChoiceType } from './types'

import { mockConnectionChoices, mockConnections } from './mocks'

import type { CDPSceneLogicType } from './CDPSceneLogicType'

export const CDPSceneLogic = kea<CDPSceneLogicType>([
    path(['scenes', 'cdp', 'CDPSceneLogic']),
    actions({
        openNewConnectionModal: true,
        closeNewConnectionModal: true,
        setTab: (tab: CDPTabsType) => ({ tab }),
    }),
    reducers({
        newConnectionModalOpen: [
            false as boolean,
            {
                openNewConnectionModal: () => true,
                closeNewConnectionModal: () => false,
            },
        ],
        connections: [mockConnections as BatchExportDestinationType[], {}],
        connectionChoices: [mockConnectionChoices as ConnectionChoiceType[], {}],
        activeTab: [
            'connections' as CDPTabsType,
            {
                setTab: (_, { tab }) => tab,
            },
        ],
    }),
])

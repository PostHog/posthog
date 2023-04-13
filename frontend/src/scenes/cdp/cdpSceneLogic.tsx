import { actions, kea, path, reducers } from 'kea'
import { CDPTabsType, ConnectionChoiceType, ConnectionType } from './types'

const mockConnections: ConnectionType[] = [
    {
        id: '1',
        name: 'Webhook export',
        status: 'Streaming',
        type: 'Event streaming',
        successRate: '100%',
        image_url: 'https://a.slack-edge.com/80588/img/services/outgoing-webhook_512.png',
    },
    {
        id: '2',
        name: 'S3 export',
        status: 'Scheduled every hour',
        type: 'Batch export',
        successRate: '100%',
        image_url: 'https://raw.githubusercontent.com/PostHog/s3-export-plugin/main/logo.png',
    },
]

const mockConnectionChoices: ConnectionChoiceType[] = [
    {
        id: '1',
        name: 'Webhook export',
        image_url: 'https://a.slack-edge.com/80588/img/services/outgoing-webhook_512.png',
        type: 'Event streaming',
    },
    {
        id: '2',
        name: 'S3 export',
        image_url: 'https://raw.githubusercontent.com/PostHog/s3-export-plugin/main/logo.png',
        type: 'Batch export',
    },
]

export const CDPSceneLogic = kea<CDPSceneLogicType>([
    path(['scenes', 'cdp', 'cdpSceneLogic']),
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
        connections: [mockConnections as ConnectionType[], {}],
        connectionChoices: [mockConnectionChoices as ConnectionChoiceType[], {}],
        activeTab: [
            'connections' as CDPTabsType,
            {
                setTab: (_, { tab }) => tab,
            },
        ],
    }),
])

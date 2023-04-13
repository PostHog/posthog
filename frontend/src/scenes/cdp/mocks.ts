import { ConnectionChoiceType, ConnectionType } from './types'

export const mockConnections: ConnectionType[] = [
    {
        id: '1',
        name: 'Webhook export',
        status: 'Streaming',
        type: 'Event streaming',
        successRate: '100%',
        imageUrl: 'https://a.slack-edge.com/80588/img/services/outgoing-webhook_512.png',
    },
    {
        id: '2',
        name: 'S3 export',
        status: 'Scheduled every hour',
        type: 'Batch export',
        successRate: '100%',
        imageUrl: 'https://raw.githubusercontent.com/PostHog/s3-export-plugin/main/logo.png',
    },
]

export const mockConnectionChoices: ConnectionChoiceType[] = [
    {
        id: 'webhook-export',
        name: 'Webhook export',
        imageUrl: 'https://a.slack-edge.com/80588/img/services/outgoing-webhook_512.png',
        type: 'Event streaming',
    },
    {
        id: 's3-export',
        name: 'S3 export',
        imageUrl: 'https://raw.githubusercontent.com/PostHog/s3-export-plugin/main/logo.png',
        type: 'Batch export',
    },
]

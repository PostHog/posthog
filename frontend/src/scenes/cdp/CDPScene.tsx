import { LemonButton, LemonTable } from '@posthog/lemon-ui'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { IconPlus } from 'lib/lemon-ui/icons'
import { SceneExport } from 'scenes/sceneTypes'

export const scene: SceneExport = {
    component: CDPScene,
    // logic: appMetricsSceneLogic,
    // paramsToProps: ({ params: { pluginConfigId } }) => ({ pluginConfigId: parseInt(pluginConfigId) ?? 0 }),
}

type ConnectionType = {
    id: string
    name: string
    status: string
    type: 'Event Streaming' | 'Batch Export'
    successRate: string
    image: string
}

const mockConnections: ConnectionType[] = [
    {
        id: '1',
        name: 'Customer.io export',
        status: 'Streaming',
        type: 'Event Streaming',
        successRate: '100%',
        image: 'https://raw.githubusercontent.com/PostHog/customerio-plugin/main/logo.png',
    },
    {
        id: '2',
        name: 'S3 export',
        status: 'Scheduled every hour',
        type: 'Batch Export',
        successRate: '100%',
        image: 'https://raw.githubusercontent.com/PostHog/s3-export-plugin/main/logo.png',
    },
]

export function ConnectionsTab(): JSX.Element {
    return (
        <LemonTable
            dataSource={mockConnections}
            columns={[
                {
                    title: 'Name',
                    dataIndex: 'name',
                    render: (_, { name, image }) => {
                        return (
                            <div className="flex items-center">
                                <div
                                    className="mr-2"
                                    style={{
                                        width: 20,
                                        height: 20,
                                        backgroundImage: `url(${image})`,
                                        backgroundSize: 'contain',
                                        backgroundRepeat: 'no-repeat',
                                    }}
                                    // eslint-disable-next-line react/no-unknown-property
                                    // onError={() => setState({ ...state, image: imgPluginDefault })}
                                />
                                <span>{name}</span>
                            </div>
                        )
                    },
                },
                {
                    title: 'Status',
                    dataIndex: 'status',
                    render: (_, { status }) => {
                        return <>{status}</>
                    },
                },
                {
                    title: 'Type',
                    dataIndex: 'type',
                    render: (_, { type }) => {
                        return <>{type}</>
                    },
                },
                {
                    title: 'Success rate (Last 24hrs)',
                    dataIndex: 'successRate',
                    render: (_, { successRate }) => {
                        return <>{successRate}</>
                    },
                },
            ]}
        />
    )
}

export function CDPScene(): JSX.Element {
    // TODO: add logic to control the tabs
    // TODO: add logic for the "New connection" button
    return (
        <>
            <PageHeader
                title="CDP"
                caption="Use connections to stream or batch export your events to other destinations"
                buttons={
                    <LemonButton type="primary" icon={<IconPlus />} data-attr="new-cdp-destination-button">
                        New connection
                    </LemonButton>
                }
            />
            <LemonTabs
                tabs={[
                    {
                        key: 'connections',
                        label: 'Connections',
                        content: <ConnectionsTab />, // TODO: come up with a better name
                    },
                    {
                        key: 'history',
                        label: 'History',
                        content: <div>History</div>,
                    },
                ]}
                activeKey={'connections'}
                onChange={console.log} // TODO
            />
        </>
    )
}

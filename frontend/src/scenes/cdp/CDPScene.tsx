import { LemonButton, LemonModal, LemonTable } from '@posthog/lemon-ui'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { IconPlus } from 'lib/lemon-ui/icons'
import { SceneExport } from 'scenes/sceneTypes'

import './CDPScene.scss'
import { FallbackCoverImage } from 'lib/components/FallbackCoverImage/FallbackCoverImage'
import clsx from 'clsx'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { ConnectionChoiceType } from './types'
import { useActions, useValues } from 'kea'
import { cdpSceneLogic } from './CDPSceneLogic'

export const scene: SceneExport = {
    component: CDPScene,
    logic: cdpSceneLogic,
    // paramsToProps: ({ params: { pluginConfigId } }) => ({ pluginConfigId: parseInt(pluginConfigId) ?? 0 }),
}

export function ConnectionsTab(): JSX.Element {
    const { connections } = useValues(cdpSceneLogic)
    return (
        <LemonTable
            dataSource={connections}
            columns={[
                {
                    title: 'Name',
                    dataIndex: 'name',
                    render: (_, { name, image_url: image }) => {
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
                                    // TODO handle fallback images
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

export function ConnectionChoice({
    connectionChoice,
    onClick,
    index,
}: {
    connectionChoice: ConnectionChoiceType
    onClick: () => void
    index: number
}): JSX.Element {
    return (
        <div
            className="ConnectionTypeGridItem cursor-pointer border rounded flex flex-col transition-all"
            onClick={onClick}
        >
            <div className={clsx('transition-all w-full overflow-hidden')}>
                <FallbackCoverImage
                    src={connectionChoice?.image_url}
                    alt="cover photo"
                    index={index}
                    imageClassName="h-40"
                    imageCover="object-contain"
                />
            </div>
            <h5 className="px-2 mb-1">{connectionChoice?.name}</h5>

            <ObjectTags className="mx-2 mb-2" tags={[connectionChoice?.type]} />
        </div>
    )
}

export function NewConnectionModal(): JSX.Element {
    const { closeNewConnectionModal } = useActions(cdpSceneLogic)
    const { newConnectionModalOpen, connectionChoices } = useValues(cdpSceneLogic)

    return (
        <LemonModal title="New connection" isOpen={newConnectionModalOpen} onClose={closeNewConnectionModal}>
            <div className="CDPScene">
                <div className="NewConnectionGrid">
                    {connectionChoices.map((connectionChoice: ConnectionChoiceType, index: number) => (
                        <ConnectionChoice
                            connectionChoice={connectionChoice}
                            onClick={() => console.log('clicked')}
                            index={index}
                            key={connectionChoice.id}
                        />
                    ))}
                </div>
            </div>
        </LemonModal>
    )
}

export function CDPScene(): JSX.Element {
    // TODO: add logic to control the tabs
    const { openNewConnectionModal } = useActions(cdpSceneLogic)
    return (
        <>
            <PageHeader
                title="CDP"
                caption="Use connections to stream or batch export your events to other destinations"
                buttons={
                    <LemonButton
                        type="primary"
                        icon={<IconPlus />}
                        data-attr="new-cdp-destination-button"
                        onClick={openNewConnectionModal}
                    >
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
            <NewConnectionModal />
        </>
    )
}

import { useValues } from 'kea'
import { Button, Menu, Dropdown, Row } from 'antd'

import { pageUrl, PathNodeData } from './pathUtils'
import { userLogic } from 'scenes/userLogic'
import { AvailableFeature, PathsFilterType } from '~/types'

import { copyToClipboard } from 'lib/utils'

import { pathsLogicType } from './pathsLogicType'
import './PathNodeCardButton.scss'

type PathNodeCardButton = {
    name: string
    count: number
    node: PathNodeData
    viewPathToFunnel: pathsLogicType['actions']['viewPathToFunnel']
    openPersonsModal: pathsLogicType['actions']['openPersonsModal']
    filter: PathsFilterType
    setFilter: (filter: PathsFilterType) => void
}

export function PathNodeCardButton({
    name,
    count,
    node,
    viewPathToFunnel,
    openPersonsModal,
    filter,
    setFilter,
}: PathNodeCardButton): JSX.Element {
    const { user } = useValues(userLogic)
    const hasAdvancedPaths = user?.organization?.available_features?.includes(AvailableFeature.PATHS_ADVANCED)

    const setAsPathStart = (): void => setFilter({ start_point: pageUrl(node) })
    const setAsPathEnd = (): void => setFilter({ end_point: pageUrl(node) })
    const excludePathItem = (): void => {
        setFilter({ exclude_events: [...(filter.exclude_events || []), pageUrl(node, false)] })
    }
    const viewFunnel = (): void => {
        viewPathToFunnel(node)
    }
    const copyName = (): void => {
        copyToClipboard(pageUrl(node))
    }
    const openModal = (): void => openPersonsModal({ path_end_key: name })

    return (
        <div className="PathNodeCardButton flex justify-between items-center w-full bg-white p-1">
            <div className="flex items-center font-semibold">
                <span className="text-xxs text-muted mr-1">{`0${name[0]}`}</span>
                <span className="text-xs">{pageUrl(node, true)}</span>
            </div>
            <Row>
                <span className="text-primary text-xs self-center pr-1 font-medium" onClick={openModal}>
                    {count}
                </span>
                <Dropdown
                    trigger={['click']}
                    overlay={
                        <Menu className="paths-options-dropdown">
                            <Menu.Item onClick={setAsPathStart}>Set as path start</Menu.Item>
                            {hasAdvancedPaths && (
                                <>
                                    <Menu.Item onClick={setAsPathEnd}>Set as path end</Menu.Item>
                                    <Menu.Item onClick={excludePathItem}>Exclude path item</Menu.Item>
                                    <Menu.Item onClick={viewFunnel}>View funnel</Menu.Item>
                                </>
                            )}
                            <Menu.Item onClick={copyName}>Copy path item name</Menu.Item>
                        </Menu>
                    }
                >
                    <div className="paths-dropdown-ellipsis">...</div>
                </Dropdown>
            </Row>
        </div>
    )
}

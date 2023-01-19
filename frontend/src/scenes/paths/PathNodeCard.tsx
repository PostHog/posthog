import { useActions, useValues } from 'kea'
import { Dropdown, Tooltip } from 'antd'

import { InsightLogicProps } from '~/types'

import { pageUrl, isSelectedPathStartOrEnd, PathNodeData } from './pathUtils'
import { pathsLogic } from './pathsLogic'
import { PathNodeCardMenu } from './PathNodeCardMenu'
import { PathNodeCardButton } from './PathNodeCardButton'

type PathNodeCardProps = {
    node: PathNodeData
    insightProps: InsightLogicProps
}

export function PathNodeCard({ node, insightProps }: PathNodeCardProps): JSX.Element | null {
    const { filter } = useValues(pathsLogic(insightProps))
    const { openPersonsModal, setFilter, viewPathToFunnel } = useActions(pathsLogic(insightProps))

    if (!node.visible) {
        return null
    }

    const isPathStart = node.targetLinks.length === 0
    const isPathEnd = node.sourceLinks.length === 0
    const continuingCount = node.sourceLinks.reduce((prev, curr) => prev + curr.value, 0)
    const dropOffCount = node.value - continuingCount
    const averageConversionTime = !isPathStart ? node.targetLinks[0].average_conversion_time / 1000 : null

    return (
        <Tooltip title={pageUrl(node)} placement="right">
            <Dropdown
                overlay={
                    <PathNodeCardMenu
                        name={node.name}
                        count={node.value}
                        continuingCount={continuingCount}
                        dropOffCount={dropOffCount}
                        averageConversionTime={averageConversionTime}
                        isPathStart={isPathStart}
                        isPathEnd={isPathEnd}
                        openPersonsModal={openPersonsModal}
                    />
                }
                placement="bottomCenter"
            >
                <div
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{
                        position: 'absolute',
                        width: 200,
                        left: isPathEnd ? node.x0 - 200 + 7 : node.x0 + 7,
                        top: isPathEnd ? node.y0 + (node.y1 - node.y0) / 2 : node.y0 + 5,
                        border: `1px solid ${isSelectedPathStartOrEnd(filter, node) ? 'purple' : 'var(--border)'}`,
                    }}
                >
                    <PathNodeCardButton
                        name={node.name}
                        count={node.value}
                        node={node}
                        viewPathToFunnel={viewPathToFunnel}
                        openPersonsModal={openPersonsModal}
                        setFilter={setFilter}
                        filter={filter}
                    />
                </div>
            </Dropdown>
        </Tooltip>
    )
}

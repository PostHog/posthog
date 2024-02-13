import { Tooltip } from '@posthog/lemon-ui'
import { Dropdown } from 'antd'
import { useActions, useValues } from 'kea'

import { InsightLogicProps } from '~/types'

import { PATH_NODE_CARD_LEFT_OFFSET, PATH_NODE_CARD_TOP_OFFSET, PATH_NODE_CARD_WIDTH } from './constants'
import { PathNodeCardButton } from './PathNodeCardButton'
import { PathNodeCardMenu } from './PathNodeCardMenu'
import { pathsDataLogic } from './pathsDataLogic'
import { isSelectedPathStartOrEnd, pageUrl, PathNodeData } from './pathUtils'

export type PathNodeCardProps = {
    insightProps: InsightLogicProps
    node: PathNodeData
}

export function PathNodeCard({ insightProps, node }: PathNodeCardProps): JSX.Element | null {
    const { pathsFilter } = useValues(pathsDataLogic(insightProps))
    const { updateInsightFilter, openPersonsModal, viewPathToFunnel } = useActions(pathsDataLogic(insightProps))

    const filter = pathsFilter || {}

    if (!node.visible) {
        return null
    }

    // Attention: targetLinks are the incoming links, sourceLinks are the outgoing links
    const isPathStart = node.targetLinks.length === 0
    const isPathEnd = node.sourceLinks.length === 0
    const continuingCount = node.sourceLinks.reduce((prev, curr) => prev + curr.value, 0)
    const dropOffCount = node.value - continuingCount
    const averageConversionTime = !isPathStart
        ? node.targetLinks.reduce((prev, curr) => prev + curr.average_conversion_time / 1000, 0) /
          node.targetLinks.length
        : null

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
                    className="absolute rounded bg-bg-light p-1"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{
                        width: PATH_NODE_CARD_WIDTH,
                        left: !isPathEnd
                            ? node.x0 + PATH_NODE_CARD_LEFT_OFFSET
                            : node.x0 + PATH_NODE_CARD_LEFT_OFFSET - PATH_NODE_CARD_WIDTH,
                        top: !isPathEnd
                            ? node.y0 + PATH_NODE_CARD_TOP_OFFSET
                            : // use middle for end nodes
                              node.y0 + (node.y1 - node.y0) / 2,
                        border: `1px solid ${isSelectedPathStartOrEnd(filter, node) ? 'purple' : 'var(--border)'}`,
                    }}
                >
                    <PathNodeCardButton
                        name={node.name}
                        count={node.value}
                        node={node}
                        viewPathToFunnel={viewPathToFunnel}
                        openPersonsModal={openPersonsModal}
                        setFilter={updateInsightFilter}
                        filter={filter}
                    />
                </div>
            </Dropdown>
        </Tooltip>
    )
}

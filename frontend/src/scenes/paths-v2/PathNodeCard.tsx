import { LemonDropdown, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { FunnelPathsFilter } from '~/queries/schema'
import { InsightLogicProps } from '~/types'

import { PathNodeCardButton } from './PathNodeCardButton'
import { PathNodeCardMenu } from './PathNodeCardMenu'
import { pathsDataLogic } from './pathsDataLogic'
import { isSelectedPathStartOrEnd, pageUrl, PathNodeData } from './pathUtils'
import {
    PATH_NODE_CARD_HEIGHT,
    PATH_NODE_CARD_LEFT_OFFSET,
    PATH_NODE_CARD_TOP_OFFSET,
    PATH_NODE_CARD_WIDTH,
} from './renderPaths'

export type PathNodeCardProps = {
    insightProps: InsightLogicProps
    node: PathNodeData
}

export function PathNodeCard({ insightProps, node }: PathNodeCardProps): JSX.Element | null {
    const { pathsFilter: _pathsFilter, funnelPathsFilter: _funnelPathsFilter } = useValues(pathsDataLogic(insightProps))
    const { updateInsightFilter, openPersonsModal, viewPathToFunnel } = useActions(pathsDataLogic(insightProps))

    const pathsFilter = _pathsFilter || {}
    const funnelPathsFilter = _funnelPathsFilter || ({} as FunnelPathsFilter)

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
            <LemonDropdown
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
                trigger="hover"
                placement="bottom"
                padded={false}
                matchWidth
            >
                <div
                    className="absolute rounded bg-bg-light p-1"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{
                        width: PATH_NODE_CARD_WIDTH,
                        height: PATH_NODE_CARD_HEIGHT,
                        left: node.x0 + PATH_NODE_CARD_LEFT_OFFSET,
                        top: node.y0 + PATH_NODE_CARD_TOP_OFFSET,
                        border: `1px solid ${
                            isSelectedPathStartOrEnd(pathsFilter, funnelPathsFilter, node) ? 'purple' : 'var(--border)'
                        }`,
                    }}
                    data-attr="path-node-card-button"
                >
                    <PathNodeCardButton
                        name={node.name}
                        count={node.value}
                        node={node}
                        viewPathToFunnel={viewPathToFunnel}
                        openPersonsModal={openPersonsModal}
                        setFilter={updateInsightFilter}
                        filter={pathsFilter}
                    />
                </div>
            </LemonDropdown>
        </Tooltip>
    )
}

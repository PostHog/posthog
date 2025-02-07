import { Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { FunnelPathsFilter } from '~/queries/schema'
import { InsightLogicProps } from '~/types'

import { PathNodeCardButton } from './PathNodeCardButton'
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

    return (
        <Tooltip title={pageUrl(node)} placement="right">
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
        </Tooltip>
    )
}

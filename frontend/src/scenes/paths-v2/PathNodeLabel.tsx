import { Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { FunnelPathsFilter } from '~/queries/schema'
import { InsightLogicProps } from '~/types'

import { PathNodeLabelButton } from './PathNodeLabelButton'
import { pathsDataLogic } from './pathsDataLogic'
import { isSelectedPathStartOrEnd, pageUrl, PathNodeData } from './pathUtils'
import { NODE_LABEL_HEIGHT, NODE_LABEL_LEFT_OFFSET, NODE_LABEL_TOP_OFFSET, NODE_LABEL_WIDTH } from './renderPaths'

export type PathNodeLabelProps = {
    insightProps: InsightLogicProps
    node: PathNodeData
}

export function PathNodeLabel({ insightProps, node }: PathNodeLabelProps): JSX.Element | null {
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
                    width: NODE_LABEL_WIDTH,
                    height: NODE_LABEL_HEIGHT,
                    left: node.x0 + NODE_LABEL_LEFT_OFFSET,
                    top: node.y0 + NODE_LABEL_TOP_OFFSET,
                    border: `1px solid ${
                        isSelectedPathStartOrEnd(pathsFilter, funnelPathsFilter, node) ? 'purple' : 'var(--border)'
                    }`,
                }}
            >
                <PathNodeLabelButton
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

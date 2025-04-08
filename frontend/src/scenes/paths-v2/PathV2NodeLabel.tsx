import { LemonButton } from '@posthog/lemon-ui'

import { InsightLogicProps } from '~/types'

import { POSTHOG_DROPOFF, POSTHOG_OTHER } from './constants'
import { PathNodeData } from './pathUtils'
import { NODE_LABEL_HEIGHT, NODE_LABEL_LEFT_OFFSET, NODE_LABEL_TOP_OFFSET, NODE_LABEL_WIDTH } from './renderPathsV2'

function formatNodeName(node: PathNodeData): string {
    if (node.name.includes(POSTHOG_DROPOFF)) {
        return 'Dropped off'
    } else if (node.name.includes(POSTHOG_OTHER)) {
        return 'Other (i.e. all remaining values)'
    }
    return node.name
}

export type PathV2NodeLabelProps = {
    insightProps: InsightLogicProps
    node: PathNodeData
}

export function PathV2NodeLabel({ node }: PathV2NodeLabelProps): JSX.Element | null {
    const openModal = (): void => {}

    return (
        <div
            className="absolute"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                width: NODE_LABEL_WIDTH,
                height: NODE_LABEL_HEIGHT,
                left: node.x0 + NODE_LABEL_LEFT_OFFSET,
                top: node.y0 + NODE_LABEL_TOP_OFFSET,
            }}
        >
            <div className="flex items-center">
                <div className="font-semibold overflow-hidden max-h-16 text-xs break-words">{formatNodeName(node)}</div>
            </div>

            <LemonButton size="xsmall" onClick={openModal} noPadding>
                <span className="font-normal">{node.value}</span>
            </LemonButton>
        </div>
    )
}

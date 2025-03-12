import { kea } from 'kea'

import type { tileVisualizationLogicType } from './tileVisualizationLogicType'
import { TileVisualizationOption } from './webAnalyticsLogic'

export interface TileVisualizationLogicProps {
    tileId: string
    tabId: string
}

// This logic manages visualization state for each tile
export const tileVisualizationLogic = kea<tileVisualizationLogicType>({
    path: () => ['scenes', 'web-analytics', 'tileVisualizationLogic'],
    props: {} as TileVisualizationLogicProps,
    key: (props) => `${props.tileId}-${props.tabId}`,
    actions: {
        setVisualization: (visualization) => ({ visualization }),
    },
    reducers: {
        visualization: [
            'table' as TileVisualizationOption,
            {
                setVisualization: (_, { visualization }) => visualization,
            },
        ],
    },
})

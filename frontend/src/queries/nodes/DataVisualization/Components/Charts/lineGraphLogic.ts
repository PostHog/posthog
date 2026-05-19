import { actions, kea, key, path, props, reducers } from 'kea'

import type { lineGraphLogicType } from './lineGraphLogicType'

export interface LineGraphLogicProps {
    key: string
}

export const lineGraphLogic = kea<lineGraphLogicType>([
    path(['queries', 'nodes', 'DataVisualization', 'Components', 'Charts', 'lineGraphLogic']),
    props({ key: '' } as LineGraphLogicProps),
    key((props) => props.key),
    actions({
        setHoveredDatasetIndex: (hoveredDatasetIndex: number | null) => ({ hoveredDatasetIndex }),
    }),
    reducers({
        hoveredDatasetIndex: [
            null as number | null,
            {
                setHoveredDatasetIndex: (_, { hoveredDatasetIndex }) => hoveredDatasetIndex,
            },
        ],
    }),
])

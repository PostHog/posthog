import { connect, kea, path, props, selectors } from 'kea'
import { resizerLogic, ResizerLogicProps } from 'lib/components/Resizer/resizerLogic'

import type { editorSizingLogicType } from './editorSizingLogicType'

interface EditorSizingLogicProps {
    editorSceneRef: React.RefObject<HTMLDivElement>
    navigatorRef: React.RefObject<HTMLDivElement>
    sourceNavigatorResizerProps: ResizerLogicProps
    queryPaneResizerProps: ResizerLogicProps
}

const MINIMUM_NAVIGATOR_WIDTH = 100
const NAVIGATOR_DEFAULT_WIDTH = 350
const MINIMUM_QUERY_PANE_HEIGHT = 100
const DEFAULT_QUERY_PANE_HEIGHT = 600

export const editorSizingLogic = kea<editorSizingLogicType>([
    path(['scenes', 'data-warehouse', 'editor', 'editorSizingLogic']),
    props({} as EditorSizingLogicProps),
    connect((props: EditorSizingLogicProps) => ({
        values: [
            resizerLogic(props.sourceNavigatorResizerProps),
            ['desiredSize as sourceNavigatorDesiredSize'],
            resizerLogic(props.queryPaneResizerProps),
            ['desiredSize as queryPaneDesiredSize'],
        ],
    })),
    selectors({
        editorSceneRef: [() => [(_, props) => props.editorSceneRef], (editorSceneRef) => editorSceneRef],
        sourceNavigatorWidth: [
            (s) => [s.sourceNavigatorDesiredSize],
            (desiredSize) => Math.max(desiredSize || NAVIGATOR_DEFAULT_WIDTH, MINIMUM_NAVIGATOR_WIDTH),
        ],
        queryPaneHeight: [
            (s) => [s.queryPaneDesiredSize],
            (queryPaneDesiredSize) =>
                Math.max(queryPaneDesiredSize || DEFAULT_QUERY_PANE_HEIGHT, MINIMUM_QUERY_PANE_HEIGHT),
        ],
        queryTabsWidth: [(s) => [s.queryPaneDesiredSize], (desiredSize) => desiredSize || NAVIGATOR_DEFAULT_WIDTH],
        sourceNavigatorResizerProps: [
            () => [(_, props) => props.sourceNavigatorResizerProps],
            (sourceNavigatorResizerProps) => sourceNavigatorResizerProps,
        ],
        queryPaneResizerProps: [
            () => [(_, props) => props.queryPaneResizerProps],
            (queryPaneResizerProps) => queryPaneResizerProps,
        ],
    }),
])

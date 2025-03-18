import { connect, kea, path, props, selectors } from 'kea'
import { resizerLogic, ResizerLogicProps } from 'lib/components/Resizer/resizerLogic'

import type { editorSizingLogicType } from './editorSizingLogicType'

export interface EditorSizingLogicProps {
    editorSceneRef: React.RefObject<HTMLDivElement>
    navigatorRef: React.RefObject<HTMLDivElement>
    sidebarRef: React.RefObject<HTMLDivElement>
    sourceNavigatorResizerProps: ResizerLogicProps
    sidebarResizerProps: ResizerLogicProps
    queryPaneResizerProps: ResizerLogicProps
}

const MINIMUM_NAVIGATOR_WIDTH = 100
const NAVIGATOR_DEFAULT_WIDTH = 350
const MINIMUM_QUERY_PANE_HEIGHT = 100
const DEFAULT_QUERY_PANE_HEIGHT = 300
const MINIMUM_SIDEBAR_WIDTH = 250
const SIDEBAR_DEFAULT_WIDTH = 350

export const editorSizingLogic = kea<editorSizingLogicType>([
    path(['scenes', 'data-warehouse', 'editor', 'editorSizingLogic']),
    props({} as EditorSizingLogicProps),
    connect((props: EditorSizingLogicProps) => ({
        values: [
            resizerLogic(props.sourceNavigatorResizerProps),
            ['desiredSize as sourceNavigatorDesiredSize'],
            resizerLogic(props.sidebarResizerProps),
            ['desiredSize as sidebarDesiredSize'],
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
        sidebarWidth: [
            // @ts-expect-error - We need to fix the typings later
            (s) => [s.sidebarDesiredSize],
            (desiredSize: number | null) => Math.max(desiredSize || SIDEBAR_DEFAULT_WIDTH, MINIMUM_SIDEBAR_WIDTH),
        ],
        sidebarResizerProps: [
            () => [(_, props) => props.sidebarResizerProps],
            (sidebarResizerProps: ResizerLogicProps) => sidebarResizerProps,
        ],
    }),
])

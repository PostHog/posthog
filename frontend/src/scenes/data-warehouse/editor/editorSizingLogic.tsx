import { actions, connect, kea, listeners, path, props, selectors } from 'kea'

import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'

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
const MINIMUM_SIDEBAR_WIDTH = 150
export const SIDEBAR_DEFAULT_WIDTH = 300
const MAXIMUM_SIDEBAR_WIDTH = 550

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
        actions: [resizerLogic(props.sidebarResizerProps), ['setDesiredSize as sidebarSetDesiredSize']],
    })),
    actions({
        resetDefaultSidebarWidth: true,
    }),
    listeners(({ actions }) => ({
        resetDefaultSidebarWidth: () => {
            actions.sidebarSetDesiredSize(SIDEBAR_DEFAULT_WIDTH)
        },
    })),
    selectors({
        editorSceneRef: [(p) => [p.editorSceneRef], (editorSceneRef) => editorSceneRef],
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
            (_, p) => [p.sourceNavigatorResizerProps],
            (sourceNavigatorResizerProps) => sourceNavigatorResizerProps,
        ],
        queryPaneResizerProps: [(_, p) => [p.queryPaneResizerProps], (queryPaneResizerProps) => queryPaneResizerProps],
        sidebarWidth: [
            (s) => [s.sidebarDesiredSize],
            (desiredSize: number | null) => {
                if (desiredSize !== null && desiredSize < MINIMUM_SIDEBAR_WIDTH / 2) {
                    return 0
                }
                return Math.min(
                    Math.max(desiredSize || SIDEBAR_DEFAULT_WIDTH, MINIMUM_SIDEBAR_WIDTH),
                    MAXIMUM_SIDEBAR_WIDTH
                )
            },
        ],
        sidebarResizerProps: [(_, p) => [p.sidebarResizerProps], (sidebarResizerProps) => sidebarResizerProps],
    }),
])

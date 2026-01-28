import { actions, connect, kea, listeners, path, props, reducers, selectors } from 'kea'

import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'

import type { editorSizingLogicType } from './editorSizingLogicType'

export interface EditorSizingLogicProps {
    editorSceneRef: React.RefObject<HTMLDivElement>
    navigatorRef: React.RefObject<HTMLDivElement>
    sidebarRef: React.RefObject<HTMLDivElement>
    databaseTreeRef: React.RefObject<HTMLDivElement>
    sourceNavigatorResizerProps: ResizerLogicProps
    sidebarResizerProps: ResizerLogicProps
    queryPaneResizerProps: ResizerLogicProps
    databaseTreeResizerProps: ResizerLogicProps
}

const MINIMUM_NAVIGATOR_WIDTH = 100
const NAVIGATOR_DEFAULT_WIDTH = 350
const MINIMUM_QUERY_PANE_HEIGHT = 100
const DEFAULT_QUERY_PANE_HEIGHT = 300
const MINIMUM_SIDEBAR_WIDTH = 150
export const SIDEBAR_DEFAULT_WIDTH = 300
const MAXIMUM_SIDEBAR_WIDTH = 550
const MINIMUM_DATABASE_TREE_WIDTH = 200
export const DATABASE_TREE_COLLAPSE_THRESHOLD = 60
const DATABASE_TREE_DEFAULT_WIDTH = 300
const MAXIMUM_DATABASE_TREE_WIDTH = 600
const DATABASE_TREE_COLLAPSED_WIDTH = 48

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
            resizerLogic(props.databaseTreeResizerProps),
            ['desiredSize as databaseTreeDesiredSize', 'isResizeInProgress as databaseTreeIsResizing'],
        ],
        actions: [
            resizerLogic(props.sidebarResizerProps),
            ['setDesiredSize as sidebarSetDesiredSize'],
            resizerLogic(props.databaseTreeResizerProps),
            ['setDesiredSize as databaseTreeSetDesiredSize', 'endResize as databaseTreeEndResize'],
        ],
    })),
    actions({
        resetDefaultSidebarWidth: true,
        toggleDatabaseTreeCollapsed: true,
        setDatabaseTreeCollapsed: (collapsed: boolean) => ({ collapsed }),
        setDatabaseTreeWillCollapse: (willCollapse: boolean) => ({ willCollapse }),
    }),
    reducers({
        isDatabaseTreeCollapsed: [
            false,
            { persist: true },
            {
                toggleDatabaseTreeCollapsed: (state) => !state,
                setDatabaseTreeCollapsed: (_, { collapsed }) => collapsed,
            },
        ],
        databaseTreeWillCollapse: [
            false,
            {
                setDatabaseTreeCollapsed: (state, { collapsed }) => (collapsed ? state : false),
                setDatabaseTreeWillCollapse: (_, { willCollapse }) => willCollapse,
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        resetDefaultSidebarWidth: () => {
            actions.sidebarSetDesiredSize(SIDEBAR_DEFAULT_WIDTH)
        },
        databaseTreeDesiredSize: (desiredSize) => {
            // Update willCollapse state based on desired size
            if (desiredSize !== null) {
                actions.setDatabaseTreeWillCollapse(desiredSize <= DATABASE_TREE_COLLAPSE_THRESHOLD)
            }
        },
        databaseTreeIsResizing: ({ isResizeInProgress }) => {
            // When resizing stops and the tree is at or below the collapse threshold, collapse it
            if (!isResizeInProgress && values.databaseTreeDesiredSize !== null) {
                if (values.databaseTreeDesiredSize <= DATABASE_TREE_COLLAPSE_THRESHOLD) {
                    actions.setDatabaseTreeCollapsed(true)
                    actions.databaseTreeSetDesiredSize(DATABASE_TREE_DEFAULT_WIDTH)
                }
            }
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
        databaseTreeWidth: [
            (s) => [s.databaseTreeDesiredSize, s.isDatabaseTreeCollapsed],
            (desiredSize: number | null, isCollapsed: boolean) => {
                if (isCollapsed) {
                    return DATABASE_TREE_COLLAPSED_WIDTH
                }
                return Math.min(
                    Math.max(desiredSize || DATABASE_TREE_DEFAULT_WIDTH, MINIMUM_DATABASE_TREE_WIDTH),
                    MAXIMUM_DATABASE_TREE_WIDTH
                )
            },
        ],
        databaseTreeResizerProps: [
            (_, p) => [p.databaseTreeResizerProps],
            (databaseTreeResizerProps) => databaseTreeResizerProps,
        ],
    }),
])

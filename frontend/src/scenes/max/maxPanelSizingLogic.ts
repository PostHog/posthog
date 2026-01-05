import { actions, connect, kea, listeners, path, props, reducers, selectors } from 'kea'

import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'

import type { maxPanelSizingLogicType } from './maxPanelSizingLogicType'

export interface MaxPanelSizingLogicProps {
    chatHistoryPanelRef: React.RefObject<HTMLDivElement>
    chatHistoryPanelResizerProps: ResizerLogicProps
}

const MINIMUM_CHAT_HISTORY_WIDTH = 200
export const CHAT_HISTORY_COLLAPSE_THRESHOLD = 60
const CHAT_HISTORY_DEFAULT_WIDTH = 280
const MAXIMUM_CHAT_HISTORY_WIDTH = 400
const CHAT_HISTORY_COLLAPSED_WIDTH = 48

export const maxPanelSizingLogic = kea<maxPanelSizingLogicType>([
    path(['scenes', 'max', 'maxPanelSizingLogic']),
    props({} as MaxPanelSizingLogicProps),
    connect((props: MaxPanelSizingLogicProps) => ({
        values: [
            resizerLogic(props.chatHistoryPanelResizerProps),
            ['desiredSize as chatHistoryPanelDesiredSize', 'isResizeInProgress as chatHistoryPanelIsResizing'],
        ],
        actions: [
            resizerLogic(props.chatHistoryPanelResizerProps),
            ['setDesiredSize as chatHistoryPanelSetDesiredSize', 'endResize as chatHistoryPanelEndResize'],
        ],
    })),
    actions({
        toggleChatHistoryPanelCollapsed: true,
        setChatHistoryPanelCollapsed: (collapsed: boolean) => ({ collapsed }),
        setChatHistoryPanelWillCollapse: (willCollapse: boolean) => ({ willCollapse }),
    }),
    reducers({
        isChatHistoryPanelCollapsed: [
            false, // Start expanded by default when AI_FIRST_EXPERIENCE is enabled
            { persist: true },
            {
                toggleChatHistoryPanelCollapsed: (state) => !state,
                setChatHistoryPanelCollapsed: (_, { collapsed }) => collapsed,
            },
        ],
        chatHistoryPanelWillCollapse: [
            false,
            {
                setChatHistoryPanelCollapsed: (state, { collapsed }) => (collapsed ? state : false),
                setChatHistoryPanelWillCollapse: (_, { willCollapse }) => willCollapse,
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        chatHistoryPanelDesiredSize: (desiredSize) => {
            // Update willCollapse state based on desired size
            if (desiredSize !== null) {
                actions.setChatHistoryPanelWillCollapse(desiredSize <= CHAT_HISTORY_COLLAPSE_THRESHOLD)
            }
        },
        chatHistoryPanelIsResizing: ({ isResizeInProgress }) => {
            // When resizing stops and the panel is at or below the collapse threshold, collapse it
            if (!isResizeInProgress && values.chatHistoryPanelDesiredSize !== null) {
                if (values.chatHistoryPanelDesiredSize <= CHAT_HISTORY_COLLAPSE_THRESHOLD) {
                    actions.setChatHistoryPanelCollapsed(true)
                    actions.chatHistoryPanelSetDesiredSize(CHAT_HISTORY_DEFAULT_WIDTH)
                }
            }
        },
    })),
    selectors({
        chatHistoryPanelWidth: [
            (s) => [s.chatHistoryPanelDesiredSize, s.isChatHistoryPanelCollapsed],
            (desiredSize: number | null, isCollapsed: boolean) => {
                if (isCollapsed) {
                    return CHAT_HISTORY_COLLAPSED_WIDTH
                }
                return Math.min(
                    Math.max(desiredSize || CHAT_HISTORY_DEFAULT_WIDTH, MINIMUM_CHAT_HISTORY_WIDTH),
                    MAXIMUM_CHAT_HISTORY_WIDTH
                )
            },
        ],
        chatHistoryPanelResizerProps: [
            (_, p) => [p.chatHistoryPanelResizerProps],
            (chatHistoryPanelResizerProps) => chatHistoryPanelResizerProps,
        ],
    }),
])

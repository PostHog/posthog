import { actions, connect, kea, listeners, path, reducers } from 'kea'
import { uuid } from 'lib/utils'
import { JSONContent } from 'scenes/notebooks/Notebook/types'

import { SidePanelTab } from '~/types'

import { sidePanelStateLogic } from '../sidePanelStateLogic'
import type { sidePanelCanvasLogicType } from './sidePanelCanvasLogicType'

export const sidePanelCanvasLogic = kea<sidePanelCanvasLogicType>([
    path(['scenes', 'navigation', 'sidepanel', 'sidePanelCanvasLogic']),
    connect({
        actions: [sidePanelStateLogic, ['openSidePanel', 'closeSidePanel']],
    }),

    actions({
        openCanvas: (title: string, canvas: JSONContent[]) => ({ title, canvas }),
    }),

    reducers(() => ({
        title: [
            'Canvas' as string,
            { persist: true },
            {
                openCanvas: (_, { title }) => title,
            },
        ],
        canvas: [
            null as JSONContent | null,
            { persist: true },
            {
                openCanvas: (_, { canvas }) => canvas,
            },
        ],

        canvasId: [
            uuid(),
            {
                openCanvas: () => uuid(),
            },
        ],
    })),

    listeners(({ actions }) => ({
        openCanvas: () => {
            actions.openSidePanel(SidePanelTab.Canvas)
        },
    })),
])

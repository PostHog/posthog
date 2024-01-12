import { actions, kea, reducers, path, listeners, connect } from 'kea'

import { sidePanelStateLogic } from '../sidePanelStateLogic'
import { SidePanelTab } from '~/types'
import { JSONContent } from 'scenes/notebooks/Notebook/utils'
import { uuid } from 'lib/utils'

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
            uuid() as string,
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

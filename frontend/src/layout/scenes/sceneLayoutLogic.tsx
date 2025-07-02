import { actions, kea, path, reducers } from 'kea'
import type { sceneLayoutLogicType } from './sceneLayoutLogicType'

export const sceneLayoutLogic = kea<sceneLayoutLogicType>([
    path(['layout', 'scene-layout', 'sceneLayoutLogic']),
    actions({
        registerScenePanelElement: (element: HTMLElement | null) => ({ element }),
        setScenePanelActive: (active: boolean) => ({ active }),
        setScenePanelOpen: (open: boolean) => ({ open }),
        setScenePanelIsOverlay: (isOverlay: boolean) => ({ isOverlay }),
    }),
    reducers({
        scenePanelElement: [
            null as HTMLElement | null,
            {
                registerScenePanelElement: (_, { element }) => element,
            },
        ],
        scenePanelActive: [
            false,
            {
                setScenePanelActive: (_, { active }) => active,
            },
        ],
        scenePanelOpen: [
            false,
            {
                setScenePanelOpen: (_, { open }) => open,
            },
        ],
        scenePanelIsOverlay: [
            true,
            {
                setScenePanelIsOverlay: (_, { isOverlay }) => isOverlay,
            },
        ],
    }),
])

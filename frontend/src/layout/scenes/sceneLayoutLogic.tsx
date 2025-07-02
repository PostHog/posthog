import { actions, kea, path, reducers } from 'kea'
import { AccessControlProps } from 'lib/components/AccessControlledLemonButton'
import { ButtonPrimitiveProps } from 'lib/ui/Button/ButtonPrimitives'
import type { sceneLayoutLogicType } from './sceneLayoutLogicType'
export type SceneHeaderItemType = 'checkbox' | 'radio' | 'toggle' | 'separator' | 'link' | 'submenu'
export type SceneHeaderItemProps = {
    title: string
    id: string
    onClick?: () => void
    to?: string
    type?: SceneHeaderItemType
    buttonProps?: ButtonPrimitiveProps
    accessControl?: AccessControlProps
}

export type SceneHeaderChildItemProps = SceneHeaderItemProps & { icon: React.ReactNode }

export const sceneLayoutLogic = kea<sceneLayoutLogicType>([
    path(['layout', 'scene-layout', 'sceneLayoutLogic']),
    actions({
        setFileActionsContainer: (element: HTMLElement | null) => ({ element }),
        setPanelInfoActive: (active: boolean) => ({ active }),
        setPanelInfoOpen: (open: boolean) => ({ open }),
        setShowPanelOverlay: (isOverlay: boolean) => ({ isOverlay }),
    }),
    reducers({
        fileActionsContainer: [
            null as HTMLElement | null,
            {
                setFileActionsContainer: (_, { element }) => element,
            },
        ],
        fileActions: [
            [] as SceneHeaderItemProps[],
            {
                setAddFileActions: (_, { actions }) => actions,
            },
        ],
        panelInfoActive: [
            false,
            {
                setPanelInfoActive: (_, { active }) => active,
            },
        ],
        panelInfoOpen: [
            false,
            {
                setPanelInfoOpen: (_, { open }) => open,
            },
        ],
        showPanelOverlay: [
            true,
            {
                setShowPanelOverlay: (_, { isOverlay }) => isOverlay,
            },
        ],
    }),
])

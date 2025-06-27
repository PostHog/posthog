import { actions, kea, path, reducers } from 'kea'
import type { sceneLayoutLogicType } from './sceneLayoutLogicType'
import { ButtonPrimitiveProps } from 'lib/ui/Button/ButtonPrimitives'
import { AccessControlProps } from 'lib/components/AccessControlledLemonButton'
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
        setAddFileActions: (actions: SceneHeaderItemProps[]) => ({ actions }),
        setAddEditActions: (actions: SceneHeaderItemProps[]) => ({ actions }),
        setAddViewActions: (actions: SceneHeaderItemProps[]) => ({ actions }),
        setAddHelpActions: (actions: SceneHeaderItemProps[]) => ({ actions }),
        setTitleRenameCallback: (callback?: (value: string) => void) => ({
            callback,
        }),
        setDescriptionRenameCallback: (callback?: (value: string) => void) => ({
            callback,
        }),
        setPanelInfoActive: (active: boolean) => ({ active }),
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
        editActions: [[] as SceneHeaderItemProps[], { setAddEditActions: (_, { actions }) => actions }],
        viewActions: [
            [] as SceneHeaderItemProps[],
            {
                setAddViewActions: (_, { actions }) => actions,
            },
        ],
        helpActions: [[] as SceneHeaderItemProps[], { setAddHelpActions: (_, { actions }) => actions }],
        panelInfoActive: [
            false,
            {
                setPanelInfoActive: (_, { active }) => active,
            },
        ],
    }),
])

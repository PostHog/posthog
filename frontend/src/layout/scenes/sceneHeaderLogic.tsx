import { actions, kea, path, reducers } from 'kea'
import { AccessControlProps } from 'lib/components/AccessControlledLemonButton'
import { ButtonPrimitiveProps } from 'lib/ui/Button/ButtonPrimitives'

import type { sceneHeaderLogicType } from './sceneHeaderLogicType'

export type SceneHeaderItemType = 'checkbox' | 'radio' | 'toggle' | 'separator' | 'link' | 'submenu'
export type SceneHeaderItemProps = {
    title: string
    id: string
    onClick?: () => void
    to?: string
    type?: SceneHeaderItemType
    buttonProps?: ButtonPrimitiveProps
    children?: SceneHeaderChildItemProps[]
    accessControl?: AccessControlProps
}

export type SceneHeaderChildItemProps = SceneHeaderItemProps & { icon: React.ReactNode }

export const sceneHeaderLogic = kea<sceneHeaderLogicType>([
    path(['layout', 'panel-layout', 'panelLayoutLogic']),
    actions({
        setFileNewProps: (items: SceneHeaderItemProps[]) => ({ items }),
        setFileNewContainer: (container: HTMLElement | null) => ({ container }),
    }),
    reducers({
        fileNewProps: [
            [] as SceneHeaderItemProps[],
            {
                setFileNewProps: (_, { items }) => items,
            },
        ],
    }),
    // listeners(({ actions, values }) => ({

    // })),
    // selectors({
    // }),
])

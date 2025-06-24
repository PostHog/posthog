import { actions, kea, path, reducers } from 'kea'
import { AccessControlProps } from 'lib/components/AccessControlledLemonButton'
import { ButtonPrimitiveProps } from 'lib/ui/Button/ButtonPrimitives'

import type { sceneHeaderLogicType } from './sceneHeaderLogicType'
import { ReactNode } from 'react'

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

interface Breadcrumb {
    name: ReactNode
    to: string
    id: string
    icon?: ReactNode
    iconColor?: string
}

export const sceneHeaderLogic = kea<sceneHeaderLogicType>([
    path(['layout', 'panel-layout', 'panelLayoutLogic']),
    actions({
        setPageTitle: (title: string) => ({ title }),
        setPageTitleEditable: (editable: boolean) => ({ editable }),
        setPageBreadcrumbs: (breadcrumbs: Breadcrumb[]) => ({ breadcrumbs }),
    }),
    reducers({
        pageTitle: [
            '' as string,
            {
                setPageTitle: (_, { title }) => title,
            },
        ],
        pageTitleEditable: [
            false as boolean,
            {
                setPageTitleEditable: (_, { editable }) => editable,
            },
        ],
        pageBreadcrumbs: [
            [] as Breadcrumb[],
            {
                setPageBreadcrumbs: (_, { breadcrumbs }) => breadcrumbs,
            },
        ],
    }),
    // listeners(({ actions, values }) => ({

    // })),
    // selectors({
    // }),
])

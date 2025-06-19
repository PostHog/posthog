import { actions, kea, path } from 'kea'

import { ButtonPrimitiveProps } from 'lib/ui/Button/ButtonPrimitives'

import type { sceneHeaderLogicType } from './sceneHeaderLogicType'

export const sceneHeaderLogic = kea<sceneHeaderLogicType>([
    path(['layout', 'panel-layout', 'panelLayoutLogic']),
    actions({
        setFileNewProps: (buttonProps: ButtonPrimitiveProps) => ({ buttonProps }),
    }),
    // reducers({

    // }),
    // listeners(({ actions, values }) => ({

    // })),
    // selectors({
    // }),
])

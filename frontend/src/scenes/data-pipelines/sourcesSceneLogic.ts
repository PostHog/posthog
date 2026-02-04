import { kea, path } from 'kea'

import { Breadcrumb } from '~/types'

import type { sourcesSceneLogicType } from './sourcesSceneLogicType'

export const sourcesSceneLogic = kea<sourcesSceneLogicType>([
    path(['scenes', 'data-pipelines', 'sourcesSceneLogic']),
    () => ({
        selectors: {
            breadcrumbs: [
                () => [],
                (): Breadcrumb[] => {
                    return [
                        {
                            key: 'Sources',
                            name: 'Sources',
                            iconType: 'data_pipeline',
                        },
                    ]
                },
            ],
        },
    }),
])

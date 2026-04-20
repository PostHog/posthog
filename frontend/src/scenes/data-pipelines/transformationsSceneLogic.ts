import { kea, path } from 'kea'

import { Breadcrumb } from '~/types'

import type { transformationsSceneLogicType } from './transformationsSceneLogicType'

export const transformationsSceneLogic = kea<transformationsSceneLogicType>([
    path(['scenes', 'data-pipelines', 'transformationsSceneLogic']),
    () => ({
        selectors: {
            breadcrumbs: [
                () => [],
                (): Breadcrumb[] => {
                    return [
                        {
                            key: 'Transformations',
                            name: 'Transformations',
                            iconType: 'data_pipeline',
                        },
                    ]
                },
            ],
        },
    }),
])

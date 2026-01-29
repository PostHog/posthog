import { kea, path } from 'kea'

import { Breadcrumb } from '~/types'

import type { destinationsSceneLogicType } from './destinationsSceneLogicType'

export const destinationsSceneLogic = kea<destinationsSceneLogicType>([
    path(['scenes', 'data-pipelines', 'destinationsSceneLogic']),
    () => ({
        selectors: {
            breadcrumbs: [
                () => [],
                (): Breadcrumb[] => {
                    return [
                        {
                            key: 'Destinations',
                            name: 'Destinations',
                            iconType: 'data_pipeline',
                        },
                    ]
                },
            ],
        },
    }),
])

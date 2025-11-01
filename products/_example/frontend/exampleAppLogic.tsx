import { afterMount, kea, path, props } from 'kea'
import { loaders } from 'kea-loaders'

import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'

import { fetchMockPersons } from '../backend/mockStore'
import { ExampleAppMockPerson } from './ExampleAppScene'
import type { exampleAppLogicType } from './exampleAppLogicType'

export const exampleAppLogic = kea<exampleAppLogicType>([
    path(['products', 'example', 'frontend', 'exampleAppLogic']),
    props({} as { tabId: string }),
    tabAwareScene(),

    loaders({
        persons: [
            [] as ExampleAppMockPerson[],
            {
                loadPersons: async () => {
                    return await fetchMockPersons()
                },
            },
        ],
    }),

    afterMount(({ actions }) => {
        actions.loadPersons()
    }),
])

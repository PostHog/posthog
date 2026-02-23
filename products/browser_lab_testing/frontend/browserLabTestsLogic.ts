import { afterMount, kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import type { browserLabTestsLogicType } from './browserLabTestsLogicType'
import type { BrowserLabTestType } from './types'

export const browserLabTestsLogic = kea<browserLabTestsLogicType>([
    path(['products', 'browser_lab_testing', 'frontend', 'browserLabTestsLogic']),
    loaders(() => ({
        browserLabTests: [
            [] as BrowserLabTestType[],
            {
                loadBrowserLabTests: async () => {
                    const response = await api.get('api/environments/@current/browser_lab_tests/')
                    return response.results
                },
            },
        ],
    })),
    afterMount(({ actions }) => {
        actions.loadBrowserLabTests()
    }),
])

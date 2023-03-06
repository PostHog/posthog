import { actions, kea, path, reducers } from 'kea'

import type { themeLogicType } from './themeLogicType'

export const themeLogic = kea<themeLogicType>([
    path(['layout', 'navigation-3000', 'themeLogic']),
    actions({
        toggleDarkMode: true,
    }),
    reducers({
        isDarkModeOn: [
            false,
            {
                persist: true,
            },
            {
                toggleDarkMode: (state) => !state,
            },
        ],
    }),
])

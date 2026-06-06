import { kea, path, reducers } from 'kea'

import type { sceneLogicType } from './sceneLogicType'

// Toolbar shim — prevents the real sceneLogic from hijacking routing.
// null sceneConfig makes themeLogic fall through to system dark mode preference.
export const sceneLogic = kea<sceneLogicType>([
    path(['toolbar', 'shims', 'sceneLogic']),
    reducers({
        sceneConfig: [null as Record<string, unknown> | null, {}],
    }),
])

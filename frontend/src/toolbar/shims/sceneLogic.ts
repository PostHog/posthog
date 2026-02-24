import { kea, path, reducers } from 'kea'

// Toolbar shim — prevents the real sceneLogic from hijacking routing.
// null sceneConfig makes themeLogic fall through to system dark mode preference.
export const sceneLogic = kea([
    path(['toolbar', 'shims', 'sceneLogic']),
    reducers({
        sceneConfig: [null as Record<string, unknown> | null, {}],
    }),
])

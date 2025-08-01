import { actions, connect, kea, path, reducers, selectors } from 'kea'
import type { sceneLayoutLogicType } from './sceneLayoutLogicType'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

export const sceneLayoutLogic = kea<sceneLayoutLogicType>([
    path(['layout', 'scene-layout', 'sceneLayoutLogic']),
    connect({ values: [featureFlagLogic, ['featureFlags']] }),
    actions({
        registerScenePanelElement: (element: HTMLElement | null) => ({ element }),
        setScenePanelIsPresent: (active: boolean) => ({ active }),
        setScenePanelOpen: (open: boolean) => ({ open }),
    }),
    reducers({
        scenePanelElement: [
            null as HTMLElement | null,
            {
                registerScenePanelElement: (_, { element }) => element,
            },
        ],
        scenePanelIsPresent: [
            false,
            {
                setScenePanelIsPresent: (_, { active }) => active,
            },
        ],
        scenePanelOpen: [
            false,
            {
                setScenePanelOpen: (_, { open }) => open,
            },
        ],
    }),
    selectors({
        useSceneTabs: [(s) => [s.featureFlags], (featureFlags) => !!featureFlags[FEATURE_FLAGS.SCENE_TABS]],
    }),
])

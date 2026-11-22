import type { BuiltLogic, LogicWrapper } from 'kea'

import { setupDetectionLogic } from './setupDetectionLogic'
import type { SceneProductEmptyState } from './types'

/** The detection logic to mount for an empty state, whichever kind it declares. */
export function emptyStateStatusLogic(emptyState: SceneProductEmptyState): BuiltLogic | LogicWrapper {
    return emptyState.detection ? setupDetectionLogic(emptyState.detection) : emptyState.statusLogic
}

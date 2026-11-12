import { FEATURE_FLAGS } from 'lib/constants'

import { toolbarPosthogJS } from '~/toolbar/shared/toolbarPosthogJS'

export function heatmapVariantFilterGateFromFlags(): boolean {
    return !!toolbarPosthogJS.getFeatureFlag(FEATURE_FLAGS.HEATMAPS_EVENT_FILTER)
}

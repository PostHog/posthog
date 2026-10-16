import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { TodayWaysToUseDialog } from './TodayWaysToUseDialog'

export function MaybeTodayWaysToUseDialog(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    return featureFlags[FEATURE_FLAGS.TODAY_RAIL_NAV] ? <TodayWaysToUseDialog /> : null
}

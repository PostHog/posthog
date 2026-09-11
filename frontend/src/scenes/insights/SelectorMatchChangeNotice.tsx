import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { hasSelectorMatchChange } from 'scenes/insights/selectorMatchChange'

import { actionsModel } from '~/models/actionsModel'
import { InsightLogicProps } from '~/types'

interface SelectorMatchChangeNoticeProps {
    insightProps: InsightLogicProps
}

// Remove after 2026-12-31, once affected owners have had a quarter to see it.
export function SelectorMatchChangeNotice({ insightProps }: SelectorMatchChangeNoticeProps): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { series } = useValues(insightVizDataLogic(insightProps))
    const { actionsById } = useValues(actionsModel)

    if (!featureFlags[FEATURE_FLAGS.SELECTOR_MATCH_CHANGE_NOTICE] || !hasSelectorMatchChange(series, actionsById)) {
        return null
    }

    return (
        <LemonBanner type="info" dismissKey={FEATURE_FLAGS.SELECTOR_MATCH_CHANGE_NOTICE}>
            Actions now match only the elements their CSS selector describes. An action in this insight matched more
            before, so these numbers are lower than they were, including for past dates.
        </LemonBanner>
    )
}

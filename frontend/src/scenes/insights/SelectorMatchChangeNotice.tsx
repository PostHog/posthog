import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { Link } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { getSelectorMatchChanges } from 'scenes/insights/selectorMatchChange'
import { urls } from 'scenes/urls'

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

    if (!featureFlags[FEATURE_FLAGS.SELECTOR_MATCH_CHANGE_NOTICE]) {
        return null
    }
    const changes = getSelectorMatchChanges(series, actionsById)
    if (changes.length === 0) {
        return null
    }

    return (
        <LemonBanner type="info" dismissKey={FEATURE_FLAGS.SELECTOR_MATCH_CHANGE_NOTICE}>
            <p>Some counts in this insight are lower than they were, including for past dates.</p>
            <p>
                Conditions written together in a selector, like a tag and a class, now have to be met by the same
                element. Before, they could come from different elements. This changed the counts for:
            </p>
            <ul className="list-disc list-inside mb-0">
                {changes.map((change) => (
                    <li key={change.actionId}>
                        <Link to={urls.action(change.actionId)}>{change.actionName}</Link>
                        {change.selectors.map((selector, index) => (
                            <span key={`${selector}-${index}`}>
                                {index === 0 ? ': ' : ', '}
                                <span className="font-mono">{selector}</span>
                            </span>
                        ))}
                    </li>
                ))}
            </ul>
        </LemonBanner>
    )
}

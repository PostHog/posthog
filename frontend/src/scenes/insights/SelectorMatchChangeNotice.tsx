import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { Link } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { getSelectorMatchChangeActionIds } from 'scenes/insights/selectorMatchChange'
import { selectorMatchChangeNoticeLogic } from 'scenes/insights/selectorMatchChangeNoticeLogic'
import { projectLogic } from 'scenes/projectLogic'
import { urls } from 'scenes/urls'

import { InsightVizNode } from '~/queries/schema/schema-general'
import { InsightLogicProps } from '~/types'

import { ActionSelectorMatchChangeApi } from 'products/actions/frontend/generated/api.schemas'

interface SelectorMatchChangeNoticeProps {
    insightProps: InsightLogicProps<InsightVizNode>
}

interface SelectorMatchChangeNoticeContentProps {
    actionIds: number[]
    projectId: number
}

// Remove after 2026-12-31, once affected owners have had a quarter to see it.
export function SelectorMatchChangeNotice({ insightProps }: SelectorMatchChangeNoticeProps): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { currentProjectId } = useValues(projectLogic)
    const { series } = useValues(insightVizDataLogic(insightProps as InsightLogicProps))

    if (!featureFlags[FEATURE_FLAGS.SELECTOR_MATCH_CHANGE_NOTICE]) {
        return null
    }
    const actionIds = getSelectorMatchChangeActionIds(series)
    if (currentProjectId === null || actionIds.length === 0) {
        return null
    }

    return <SelectorMatchChangeNoticeContent actionIds={actionIds} projectId={currentProjectId} />
}

function SelectorMatchChangeNoticeContent({
    actionIds,
    projectId,
}: SelectorMatchChangeNoticeContentProps): JSX.Element | null {
    const { selectorMatchChanges } = useValues(selectorMatchChangeNoticeLogic({ actionIds, projectId }))

    if (!selectorMatchChanges?.length) {
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
                {selectorMatchChanges.map((change: ActionSelectorMatchChangeApi) => (
                    <li key={change.action_id}>
                        <Link to={urls.action(change.action_id)}>{change.action_name || 'Untitled action'}</Link>
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

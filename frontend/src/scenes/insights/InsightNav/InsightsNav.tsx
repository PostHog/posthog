import { useActions, useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { insightNavLogic } from 'scenes/insights/InsightNav/insightNavLogic'
import { insightTypeURL } from 'scenes/insights/utils'
import { INSIGHT_TYPES_METADATA } from 'scenes/saved-insights/SavedInsights'

import { insightLogic } from '../insightLogic'
import { FunnelsCue } from '../views/Trends/FunnelsCue'

export function InsightsNav(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { activeView, tabs } = useValues(insightNavLogic(insightProps))
    const { setActiveView } = useActions(insightNavLogic(insightProps))

    const insightTypeUrls = insightTypeURL(
        Boolean(featureFlagLogic.findMounted()?.values.featureFlags?.[FEATURE_FLAGS.BI_VIZ])
    )

    return (
        <>
            <FunnelsCue />
            <LemonTabs
                activeKey={activeView}
                onChange={(newKey) => setActiveView(newKey)}
                tabs={tabs.map(({ label, type, dataAttr }) => ({
                    key: type,
                    label: (
                        <Link to={insightTypeUrls[type]} preventClick data-attr={dataAttr}>
                            <Tooltip placement="top" title={INSIGHT_TYPES_METADATA[type].description}>
                                {label}
                            </Tooltip>
                        </Link>
                    ),
                }))}
            />
        </>
    )
}

import { useActions, useValues } from 'kea'

import { AlertDeletionWarning } from 'lib/components/Alerts/AlertDeletionWarning'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { insightNavLogic } from 'scenes/insights/InsightNav/insightNavLogic'
import { INSIGHT_TYPE_URLS } from 'scenes/insights/utils'
import { INSIGHT_TYPES_METADATA } from 'scenes/saved-insights/SavedInsights'

import { insightLogic } from '../insightLogic'

export function InsightsNav(): JSX.Element {
    const { insightProps, insight } = useValues(insightLogic)
    const { activeView, tabs } = useValues(insightNavLogic(insightProps))
    const { setActiveView } = useActions(insightNavLogic(insightProps))
    // TODO(insight-editor-panels): Replace hardcoded `true` with the feature flag before merging
    const editorPanelsEnabled = true
    useFeatureFlag('PRODUCT_ANALYTICS_INSIGHT_EDITOR_PANELS') // keep hook call for rules-of-hooks

    return (
        <>
            {insight.short_id && <AlertDeletionWarning />}
            {editorPanelsEnabled ? (
                <div className="py-1">
                    <LemonSelect
                        size="small"
                        value={activeView}
                        onChange={(newKey) => setActiveView(newKey)}
                        options={tabs.map(({ label, type }) => {
                            const Icon = INSIGHT_TYPES_METADATA[type]?.icon
                            return {
                                value: type,
                                label,
                                icon: Icon ? <Icon /> : undefined,
                            }
                        })}
                        dropdownMatchSelectWidth={false}
                    />
                </div>
            ) : (
                <LemonTabs
                    activeKey={activeView}
                    onChange={(newKey) => setActiveView(newKey)}
                    tabs={tabs.map(({ label, type, dataAttr }) => ({
                        key: type,
                        label: (
                            <Link to={INSIGHT_TYPE_URLS[type]} preventClick data-attr={dataAttr}>
                                <Tooltip
                                    placement="top"
                                    title={
                                        INSIGHT_TYPES_METADATA[type].tooltipDescription ||
                                        INSIGHT_TYPES_METADATA[type].description
                                    }
                                    docLink={INSIGHT_TYPES_METADATA[type].tooltipDocLink}
                                >
                                    <span>{label}</span>
                                </Tooltip>
                            </Link>
                        ),
                    }))}
                />
            )}
        </>
    )
}

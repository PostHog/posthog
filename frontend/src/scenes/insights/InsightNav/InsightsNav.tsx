import { useActions, useValues } from 'kea'

import { AlertDeletionWarning } from 'lib/components/Alerts/AlertDeletionWarning'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { insightNavLogic } from 'scenes/insights/InsightNav/insightNavLogic'
import { INSIGHT_TYPES_METADATA } from 'scenes/saved-insights/SavedInsights'

import { insightLogic } from '../insightLogic'
import { FunnelsCue } from '../views/Trends/FunnelsCue'

export function InsightsNav(): JSX.Element {
    const { insightProps, insight } = useValues(insightLogic)
    const { activeView, tabs } = useValues(insightNavLogic(insightProps))
    const { setActiveView } = useActions(insightNavLogic(insightProps))

    return (
        <>
            <FunnelsCue />
            {insight.short_id && <AlertDeletionWarning />}
            <div className="flex items-center gap-2">
                <span>Insight type:</span>
                <div className="flex items-center gap-1" data-attr="insight-type-selector">
                    {tabs.map((tab) => (
                        <LemonButton
                            onClick={() => setActiveView(tab.type)}
                            key={tab.type}
                            type={tab.type === activeView ? 'primary' : 'secondary'}
                            size="xsmall"
                            data-attr={tab.dataAttr}
                            tooltip={
                                INSIGHT_TYPES_METADATA[tab.type].tooltipDescription ||
                                INSIGHT_TYPES_METADATA[tab.type].description
                            }
                        >
                            {tab.label}
                        </LemonButton>
                    ))}
                </div>
            </div>
            {/*<LemonTabs*/}
            {/*    activeKey={activeView}*/}
            {/*    onChange={(newKey) => setActiveView(newKey)}*/}
            {/*    tabs={tabs.map(({ label, type, dataAttr }) => ({*/}
            {/*        key: type,*/}
            {/*        label: (*/}
            {/*            <Link to={INSIGHT_TYPE_URLS[type]} preventClick data-attr={dataAttr}>*/}
            {/*                <Tooltip*/}
            {/*                    placement="top"*/}
            {/*                    title={*/}
            {/*                        INSIGHT_TYPES_METADATA[type].tooltipDescription ||*/}
            {/*                        INSIGHT_TYPES_METADATA[type].description*/}
            {/*                    }*/}
            {/*                    docLink={INSIGHT_TYPES_METADATA[type].tooltipDocLink}*/}
            {/*                >*/}
            {/*                    <span>{label}</span>*/}
            {/*                </Tooltip>*/}
            {/*            </Link>*/}
            {/*        ),*/}
            {/*    }))}*/}
            {/*/>*/}
        </>
    )
}

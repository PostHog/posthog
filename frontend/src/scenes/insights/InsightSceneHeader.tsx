import { useValues } from 'kea'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { DebugCHQueries } from 'lib/components/AppShortcuts/utils/DebugCHQueries'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { ReloadInsight } from 'scenes/saved-insights/ReloadInsight'
import { urls } from 'scenes/urls'

import { InsightShortId, InsightLogicProps, ItemMode } from '~/types'

import { insightDataLogic } from './insightDataLogic'
import { InsightsNav } from './InsightNav/InsightsNav'
import { InsightPageHeader } from './InsightPageHeader'

export interface InsightSceneHeaderProps {
    insightLogicProps: InsightLogicProps
}

export function InsightSceneHeader({ insightLogicProps }: InsightSceneHeaderProps): JSX.Element {
    const { insightMode, hasOverrides, freshQuery } = useValues(insightSceneLogic)
    const { showDebugPanel } = useValues(insightDataLogic(insightLogicProps))
    const { insight } = useValues(insightLogic(insightLogicProps))
    const editorPanelsEnabled = useFeatureFlag('PRODUCT_ANALYTICS_SIMPLE_EDITOR', 'test')
    const insightId = insightLogicProps.dashboardItemId

    return (
        <>
            <InsightPageHeader insightLogicProps={insightLogicProps} />

            {hasOverrides && insightId && (
                <LemonBanner type="warning" className="mb-4">
                    <div className="flex flex-row items-center justify-between gap-2">
                        <span>
                            You are viewing this insight with filter/variable overrides. Discard them to edit the
                            insight.
                        </span>

                        <LemonButton type="secondary" to={urls.insightView(insightId as InsightShortId)}>
                            Discard overrides
                        </LemonButton>
                    </div>
                </LemonBanner>
            )}

            {insightMode === ItemMode.Edit &&
                (editorPanelsEnabled ? (
                    <div className="[&_.LemonTabs]:![--lemon-tabs-margin-bottom:0]">
                        <InsightsNav />
                    </div>
                ) : (
                    <InsightsNav />
                ))}

            {showDebugPanel && insight?.id && (
                <div className="mb-4">
                    <DebugCHQueries insightId={insight.id} />
                </div>
            )}

            {freshQuery ? <ReloadInsight /> : null}
        </>
    )
}

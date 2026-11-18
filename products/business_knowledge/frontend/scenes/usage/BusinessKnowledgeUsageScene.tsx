import { useActions, useValues } from 'kea'

import { LemonBanner, LemonCard, LemonSegmentedButton, LemonSkeleton } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { Sparkline } from 'lib/components/Sparkline'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { pluralize } from 'lib/utils/strings'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { BusinessKnowledgeTabs } from '../../components/BusinessKnowledgeTabs/BusinessKnowledgeTabs'
import { USAGE_PERIOD_DAYS, businessKnowledgeUsageLogic } from './businessKnowledgeUsageLogic'
import { UsageSummary } from './UsageSummary'
import { UsageTopSourcesTable } from './UsageTopSourcesTable'

export const scene: SceneExport = {
    component: BusinessKnowledgeUsageScene,
    logic: businessKnowledgeUsageLogic,
    productKey: ProductKey.BUSINESS_KNOWLEDGE,
}

export function BusinessKnowledgeUsageScene(): JSX.Element {
    const isEnabled = useFeatureFlag('PRODUCT_BUSINESS_KNOWLEDGE')
    const { usage, usageLoading, usageLoadFailed, days, dailyCounts, dailyLabels } =
        useValues(businessKnowledgeUsageLogic)
    const { setDays, loadUsage } = useActions(businessKnowledgeUsageLogic)

    if (!isEnabled) {
        return <NotFound object="Business knowledge" caption="This feature is not enabled for your project." />
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name="Business knowledge"
                description="Upload text, public URLs, or files so AI can understand your business context, vision, and policies."
                resourceType={{ type: 'business_knowledge' }}
            />
            <BusinessKnowledgeTabs activeTab="usage" />
            <SceneSection
                title="Usage"
                description="How often the support agent cited your knowledge when it worked on a ticket."
                className="gap-y-2"
                actions={
                    <LemonSegmentedButton
                        size="small"
                        value={days}
                        onChange={setDays}
                        options={USAGE_PERIOD_DAYS.map((period) => ({
                            value: period,
                            label: `${period} days`,
                            // pinned: autocapture / Playwright key. Do not rename.
                            'data-attr': `business-knowledge-usage-period-${period}`,
                        }))}
                    />
                }
            >
                {usageLoadFailed ? (
                    <LemonBanner type="error" action={{ children: 'Try again', onClick: () => loadUsage() }}>
                        Couldn't load usage. Try again, and if it keeps happening contact support.
                    </LemonBanner>
                ) : !usage ? (
                    <div className="flex flex-col gap-2">
                        <LemonSkeleton className="h-20 w-full" />
                        <LemonSkeleton className="h-48 w-full" />
                    </div>
                ) : usage.cited_run_count === 0 ? (
                    <LemonCard hoverEffect={false} className="p-3">
                        <p className="m-0 text-sm text-secondary">
                            No agent run cited your knowledge in the last {pluralize(usage.days, 'day')}. The support
                            agent cites a source when it uses it on a ticket. Add sources that cover common support
                            questions, and check that the support agent is turned on.
                        </p>
                    </LemonCard>
                ) : (
                    <div className="flex flex-col gap-2">
                        <UsageSummary usage={usage} />
                        <LemonCard hoverEffect={false} className="flex flex-col gap-2 p-3">
                            <span className="text-sm text-secondary">Agent runs that cited knowledge, per day</span>
                            <Sparkline
                                type="bar"
                                className="h-24 w-full"
                                data={dailyCounts}
                                labels={dailyLabels}
                                name="Agent runs"
                                loading={usageLoading}
                            />
                        </LemonCard>
                        <SceneSection title="Most cited sources" titleSize="sm" className="gap-y-2">
                            <UsageTopSourcesTable sources={usage.top_sources} />
                        </SceneSection>
                    </div>
                )}
            </SceneSection>
        </SceneContent>
    )
}

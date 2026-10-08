import { useValues } from 'kea'

import { insightReadsFlagCalls } from 'lib/components/FlagCalledRebuildBanner/flagCalledDependencies'
import { FlagCalledRebuildBanner } from 'lib/components/FlagCalledRebuildBanner/FlagCalledRebuildBanner'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { urls } from 'scenes/urls'

import { InsightLogicProps, ItemMode } from '~/types'

import { insightDataLogic } from './insightDataLogic'
import { insightLogic } from './insightLogic'

export function InsightFlagCalledBanner({ insightProps }: { insightProps: InsightLogicProps }): JSX.Element {
    const { insightMode } = useValues(insightSceneLogic)
    const { insight, canEditInsight } = useValues(insightLogic(insightProps))
    // Reads the live query, so the banner clears as soon as the editor rebuilds the series.
    const { query } = useValues(insightDataLogic(insightProps))

    return (
        <FlagCalledRebuildBanner
            artifactType="insight"
            readsFlagCalls={insightReadsFlagCalls(query)}
            action={
                insightMode !== ItemMode.Edit && canEditInsight && insight.short_id
                    ? {
                          children: 'Edit insight',
                          to: urls.insightEdit(insight.short_id),
                          'data-attr': 'flag-called-rebuild-banner-edit-insight',
                      }
                    : undefined
            }
        >
            This insight won't show feature flag calls made after your organization's flag calls move out of the events
            table. To rebuild it, replace each series that uses Feature flag called, directly or through an action, with
            a new Feature flag called series.
        </FlagCalledRebuildBanner>
    )
}

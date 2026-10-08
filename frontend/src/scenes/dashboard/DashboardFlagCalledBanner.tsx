import { useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import {
    combineReferences,
    insightFlagCalledReferences,
} from 'lib/components/FlagCalledRebuildBanner/flagCalledDependencies'
import { FlagCalledRebuildBanner } from 'lib/components/FlagCalledRebuildBanner/FlagCalledRebuildBanner'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { DashboardPlacement } from '~/types'

import { dashboardLogic } from './dashboardLogic'

export function DashboardFlagCalledBanner(): JSX.Element | null {
    const { insightTiles, placement } = useValues(dashboardLogic)

    // Shared and exported views have nobody who can rebuild the insights.
    // A flag's Usage tab renders the usage dashboard that PostHog generated, which the customer did not build.
    if (
        placement === DashboardPlacement.Public ||
        placement === DashboardPlacement.Export ||
        placement === DashboardPlacement.FeatureFlag
    ) {
        return null
    }
    // A viewer without access to an insight gets its tile without a query.
    const tiles = (insightTiles ?? []).flatMap(({ insight }) =>
        insight?.query ? [{ insight, references: insightFlagCalledReferences(insight.query) }] : []
    )

    return (
        <FlagCalledRebuildBanner
            artifactType="dashboard"
            references={combineReferences(tiles.map(({ references }) => references))}
            className="mt-4 mb-2"
        >
            {(dependsOn) => {
                const affectedInsights = tiles
                    .filter(({ references }) => dependsOn(references))
                    .map(({ insight }) => insight)
                return (
                    <>
                        <span>{pluralize(affectedInsights.length, 'insight')}</span> on this dashboard won't show new
                        feature flag calls once your organization's flag calls move out of the events table. Open each
                        one to rebuild it:{' '}
                        {/* Elements, not bare text, so page translation can't break list updates (react#11538). */}
                        {affectedInsights.map((insight, index) => (
                            <span key={insight.short_id}>
                                {index > 0 && <span>, </span>}
                                <Link to={urls.insightView(insight.short_id)}>
                                    {insight.name || insight.derived_name || 'Untitled'}
                                </Link>
                            </span>
                        ))}
                    </>
                )
            }}
        </FlagCalledRebuildBanner>
    )
}

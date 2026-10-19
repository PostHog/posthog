import { useActions, useValues } from 'kea'

import { IconArrowRight, IconStarFilled } from '@posthog/icons'
import { LemonCard, Tooltip, Link } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { DashboardByProductPreview } from './DashboardByProductPreview'
import { dashboardsByProductLogic } from './dashboardsByProductLogic'

export function DashboardsByProduct(): JSX.Element | null {
    const { reportDashboardByProductClicked } = useActions(eventUsageLogic)
    const { visibleDashboards, starredProductIds } = useValues(dashboardsByProductLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const flag = featureFlags[FEATURE_FLAGS.DASHBOARDS_BY_PRODUCT]

    if (flag !== true && flag !== 'test') {
        return null
    }

    return (
        <section aria-label="Dashboards by product" className="@container pb-8">
            <h2 className="text-base font-semibold mb-1">Dashboards by product</h2>
            <p className="text-muted mb-3">Ready-made dashboards for the PostHog products you use.</p>
            <div className="grid grid-cols-1 @min-[32rem]:grid-cols-2 @min-[64rem]:grid-cols-3 @min-[100rem]:grid-cols-4 gap-3">
                {visibleDashboards.map((dashboard) => (
                    <Link
                        key={dashboard.key}
                        to={dashboard.url}
                        onClickCapture={() => reportDashboardByProductClicked(dashboard.key)}
                        onAuxClick={(event) => {
                            if (event.button === 1) {
                                reportDashboardByProductClicked(dashboard.key)
                            }
                        }}
                        data-attr={`dashboard-by-product-${dashboard.key}`}
                        className="DashboardsByProduct__card group block min-w-0 text-primary hover:text-primary rounded focus-visible:outline focus-visible:outline-accent"
                    >
                        <LemonCard hoverEffect={false} className="h-full overflow-hidden p-0 group-hover:border-accent">
                            <div className={dashboard.color}>
                                <DashboardByProductPreview kind={dashboard.key} />
                            </div>
                            <div className="p-4">
                                <div className="flex items-center justify-between gap-2 mb-1">
                                    <div className="flex items-center gap-2 min-w-0">
                                        <h3 className="text-sm font-semibold mb-0">{dashboard.title}</h3>
                                        {starredProductIds[dashboard.sidebarPath] && (
                                            <Tooltip title="Starred in sidebar">
                                                <span
                                                    className="flex shrink-0 text-warning"
                                                    role="img"
                                                    aria-label="Starred in sidebar"
                                                >
                                                    <IconStarFilled aria-hidden="true" />
                                                </span>
                                            </Tooltip>
                                        )}
                                    </div>
                                    <IconArrowRight className="text-muted shrink-0" aria-hidden="true" />
                                </div>
                                <p className="text-muted text-sm mb-0">{dashboard.description}</p>
                            </div>
                        </LemonCard>
                    </Link>
                ))}
            </div>
        </section>
    )
}

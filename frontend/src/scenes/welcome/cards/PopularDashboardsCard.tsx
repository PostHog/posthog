import { useActions, useValues } from 'kea'

import { IconDashboard } from '@posthog/icons'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { Link } from 'lib/lemon-ui/Link'

import { PRODUCT_BRANDING } from '../productBranding'
import { welcomeDialogLogic } from '../welcomeDialogLogic'

const PA_RGB = PRODUCT_BRANDING.product_analytics.rgb

export function PopularDashboardsCard(): JSX.Element | null {
    const { popularDashboards } = useValues(welcomeDialogLogic)
    const { trackCardClick } = useActions(welcomeDialogLogic)

    if (popularDashboards.length === 0) {
        return null
    }

    return (
        <LemonCard hoverEffect={false} className="p-4">
            <h2 className="text-lg font-semibold mb-3">Popular dashboards</h2>
            <ul className="flex flex-col gap-3 m-0 p-0 list-none">
                {popularDashboards.map((dashboard) => (
                    <li key={dashboard.id} className="flex items-start gap-3">
                        <div
                            className="flex-shrink-0 w-8 h-8 rounded-md flex items-center justify-center"
                            /* eslint-disable-next-line react/forbid-dom-props */
                            style={{
                                backgroundColor: `rgb(${PA_RGB} / 0.12)`,
                                color: `rgb(${PA_RGB})`,
                            }}
                            aria-hidden="true"
                        >
                            <IconDashboard className="text-lg" />
                        </div>
                        <div className="flex-1 min-w-0 text-sm leading-snug">
                            <Link
                                to={dashboard.url}
                                subtle
                                onClick={() => trackCardClick('dashboards', dashboard.url)}
                                className="font-medium break-words"
                            >
                                {dashboard.name}
                            </Link>
                            {dashboard.description ? (
                                <div className="text-xs text-muted truncate">{dashboard.description}</div>
                            ) : null}
                        </div>
                    </li>
                ))}
            </ul>
        </LemonCard>
    )
}

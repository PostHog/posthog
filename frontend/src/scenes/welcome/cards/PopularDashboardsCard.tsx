import { useActions, useValues } from 'kea'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { Link } from 'lib/lemon-ui/Link'

import { welcomeDialogLogic } from '../welcomeDialogLogic'

export function PopularDashboardsCard(): JSX.Element | null {
    const { popularDashboards } = useValues(welcomeDialogLogic)
    const { trackCardClick } = useActions(welcomeDialogLogic)

    if (popularDashboards.length === 0) {
        return null
    }

    return (
        <LemonCard hoverEffect={false} className="p-6">
            <h2 className="text-lg font-semibold mb-3">Popular dashboards</h2>
            <ul className="flex flex-col gap-2">
                {popularDashboards.map((dashboard) => (
                    <li key={dashboard.id} className="text-sm">
                        <Link to={dashboard.url} onClick={() => trackCardClick('dashboards', dashboard.url)}>
                            <span className="font-medium">{dashboard.name}</span>
                        </Link>
                        {dashboard.description ? (
                            <div className="text-xs text-muted truncate">{dashboard.description}</div>
                        ) : null}
                    </li>
                ))}
            </ul>
        </LemonCard>
    )
}

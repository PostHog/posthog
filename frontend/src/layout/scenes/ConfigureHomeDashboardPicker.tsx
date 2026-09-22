import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { LemonSearchableSelect, LemonSelectOptions } from '@posthog/lemon-ui'

import { dashboardsModel } from '~/models/dashboardsModel'
import { sceneLogic } from '~/scenes/sceneLogic'
import { emptySceneParams } from '~/scenes/scenes'
import { Scene } from '~/scenes/sceneTypes'
import { teamLogic } from '~/scenes/teamLogic'
import { urls } from '~/scenes/urls'

export function ConfigureHomeDashboardPicker({ onSelect }: { onSelect: () => void }): JSX.Element {
    const { nameSortedDashboards, dashboardsLoading } = useValues(dashboardsModel)
    const { currentTeam } = useValues(teamLogic)
    const { setHomepage } = useActions(sceneLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const options: LemonSelectOptions<number | null> = [
        { value: null, label: 'No default dashboard / show the "new tab" page' },
        ...nameSortedDashboards.map((dashboard) => ({ value: dashboard.id, label: dashboard.name || 'Untitled' })),
    ]

    return (
        <LemonSearchableSelect<number | null>
            className="w-full"
            fullWidth
            options={options}
            value={currentTeam?.primary_dashboard ?? null}
            searchPlaceholder="Search dashboards…"
            searchInputDataAttr="configure-home-modal-default-dashboard-search"
            data-attr="configure-home-modal-set-default-dashboard-select"
            onChange={(dashboardId) => {
                posthog.capture('homepage configure default dashboard changed')
                updateCurrentTeam({ primary_dashboard: dashboardId ?? null })
                if (dashboardId) {
                    onSelect()
                    setHomepage({
                        id: `homepage-dashboard-${dashboardId}`,
                        pathname: urls.dashboard(dashboardId),
                        search: '',
                        hash: '',
                        title: 'Default dashboard',
                        iconType: 'dashboard',
                        sceneId: Scene.Dashboard,
                        sceneKey: `dashboard-${dashboardId}`,
                        sceneParams: emptySceneParams,
                    })
                }
            }}
            disabledReason={dashboardsLoading ? 'Loading dashboards…' : undefined}
        />
    )
}

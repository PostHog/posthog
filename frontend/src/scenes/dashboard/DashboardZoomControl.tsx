import { useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { AppShortcut } from 'lib/components/AppShortcuts/AppShortcut'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { Scene } from 'scenes/sceneTypes'

import { dashboardLogic } from './dashboardLogic'

interface DashboardZoomControlProps {
    layoutZoom: number
    setLayoutZoom: (value: number) => void
}

export function DashboardZoomControl({ layoutZoom, setLayoutZoom }: DashboardZoomControlProps): JSX.Element | null {
    const { dashboard, currentLayoutSize } = useValues(dashboardLogic)

    if (currentLayoutSize === 'xs') {
        return null
    }

    return (
        <div className="flex items-center gap-2 text-sm text-muted hidden md:flex">
            <AppShortcut
                name="DashboardLayoutZoomToggle"
                keybind={[['z']]}
                intent="Toggle dashboard layout zoom while editing"
                interaction="click"
                scope={Scene.Dashboard}
            >
                <LemonButton
                    size="small"
                    type="secondary"
                    active={layoutZoom < 1}
                    onClick={() => {
                        const nextZoom = layoutZoom < 1 ? 1 : 0.25
                        setLayoutZoom(nextZoom)
                        eventUsageLogic.actions.reportDashboardLayoutZoomChanged(dashboard ?? null, nextZoom, 'button')
                    }}
                    tooltip="Collapse/Expand view. Makes it easier to edit the layout for busier dashboards."
                >
                    {layoutZoom < 1 ? 'Expand view' : 'Collapse view'}
                </LemonButton>
            </AppShortcut>
        </div>
    )
}

import { useValues } from 'kea'

import { IconMinus, IconPlus } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { AppShortcut } from 'lib/components/AppShortcuts/AppShortcut'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { Scene } from 'scenes/sceneTypes'

import { dashboardLogic } from './dashboardLogic'

interface DashboardZoomControlProps {
    layoutZoom: number
    setLayoutZoom: (value: number) => void
}

export function DashboardZoomControl({ layoutZoom, setLayoutZoom }: DashboardZoomControlProps): JSX.Element | null {
    const { dashboard, currentLayoutSize } = useValues(dashboardLogic)
    const showLayoutZoom = useFeatureFlag('DASHBOARD_LAYOUT_ZOOM')
    const isSmallLayout = currentLayoutSize === 'xs'

    if (!showLayoutZoom) {
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
                disabled={isSmallLayout}
            >
                <LemonButton
                    size="small"
                    type="secondary"
                    active={layoutZoom < 1}
                    onClick={() => {
                        const nextZoom = layoutZoom <= 0.75 ? 1 : 0.25
                        setLayoutZoom(nextZoom)
                        eventUsageLogic.actions.reportDashboardLayoutZoomChanged(dashboard ?? null, nextZoom, 'toggle')
                    }}
                    tooltip="Toggle zoom level. Makes it easier to edit the layout for busier dashboards."
                >
                    {layoutZoom < 1 ? <IconPlus className="size-4 mr-1" /> : <IconMinus className="size-4 mr-1" />}
                    {layoutZoom < 1 ? 'Zoom in' : 'Zoom out'}
                </LemonButton>
            </AppShortcut>
        </div>
    )
}

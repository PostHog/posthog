import { useValues } from 'kea'

import { IconSearch } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { useAppShortcut } from 'lib/components/AppShortcuts/useAppShortcut'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonSlider } from 'lib/lemon-ui/LemonSlider'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { Scene } from 'scenes/sceneTypes'

import { dashboardLogic } from './dashboardLogic'

interface DashboardZoomControlProps {
    layoutZoom: number
    setLayoutZoom: (value: number) => void
}

export function DashboardZoomControl({ layoutZoom, setLayoutZoom }: DashboardZoomControlProps): JSX.Element | null {
    const { dashboard } = useValues(dashboardLogic)
    const showLayoutZoom = useFeatureFlag('DASHBOARD_LAYOUT_ZOOM')

    useAppShortcut({
        name: 'dashboard-layout-zoom-toggle',
        keybind: [['z']],
        intent: 'Toggle dashboard layout zoom while editing',
        scope: Scene.Dashboard,
        interaction: 'function',
        disabled: !showLayoutZoom,
        callback: () => {
            const nextZoom = layoutZoom <= 0.75 ? 1 : 0.5
            setLayoutZoom(nextZoom)
            eventUsageLogic.actions.reportDashboardLayoutZoomChanged(dashboard ?? null, nextZoom, 'shortcut')
        },
    })

    if (!showLayoutZoom) {
        return null
    }

    return (
        <Tooltip
            title="Zoom only affects layout editing to make it easier to rearrange tiles. It doesn't change how the dashboard looks when viewing. Press Z to toggle between zoom levels while editing."
            placement="bottom"
        >
            <div className="flex items-center gap-2 text-sm text-muted hidden md:flex">
                <span className="inline-flex items-center gap-1">
                    <IconSearch className="size-3" />
                    Zoom
                </span>
                <LemonSlider
                    min={0.5}
                    max={1}
                    step={0.05}
                    value={layoutZoom}
                    onChange={(value) => {
                        const nextZoom = Number((value as number).toFixed(2))
                        setLayoutZoom(nextZoom)
                        eventUsageLogic.actions.reportDashboardLayoutZoomChanged(dashboard ?? null, nextZoom, 'slider')
                    }}
                    className="max-w-40"
                />
            </div>
        </Tooltip>
    )
}

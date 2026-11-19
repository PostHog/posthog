import { useActions, useValues } from 'kea'

import { IconPlus, IconRefresh } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { DisplayMenu, displayOf, useDisplay } from '../editor/display'
import { panelEditorChoiceLogic } from '../editor/panelEditorChoiceLogic'
import { panelEditorLogic } from '../editor/panelEditorLogic'
import { newPanel } from '../explore/build'
import { editorFor, useEditorPref } from '../lib/editor'
import { dashboardV2Logic } from './dashboardV2Logic'
import { DashboardV2TimeRange } from './DashboardV2TimeRange'
import { DashboardV2Variables } from './DashboardV2Variables'

export function DashboardV2Toolbar(): JSX.Element {
    const { spec, timeRange, viewChanged, dashboardLoading } = useValues(dashboardV2Logic)
    const { setTimeRange, resetView, refresh, saveSpec } = useActions(dashboardV2Logic)
    const { addPanel } = useActions(panelEditorLogic)
    const { setGalleryOpen } = useActions(panelEditorChoiceLogic)
    const simple = editorFor(useEditorPref(), useDisplay()) === 'simple'

    return (
        <div className="flex flex-wrap items-center gap-2" data-attr="dashboard-v2-toolbar">
            <DashboardV2Variables />
            <div className="ms-auto flex flex-wrap items-center gap-2">
                {viewChanged && (
                    <Button
                        variant="link-muted"
                        tooltip="Go back to the saved time range and filters"
                        onClick={() => resetView()}
                        data-attr="dashboard-v2-reset-view"
                    >
                        Reset view
                    </Button>
                )}
                <DashboardV2TimeRange from={timeRange.from} to={timeRange.to} onChange={setTimeRange} />
                <Button
                    variant="outline"
                    size="icon"
                    aria-label="Refresh"
                    tooltip="Refresh"
                    loading={dashboardLoading}
                    onClick={() => refresh()}
                    data-attr="dashboard-v2-refresh"
                >
                    <IconRefresh />
                </Button>
                {spec && (
                    <DisplayMenu
                        value={displayOf(spec)}
                        onChange={(display) => saveSpec({ spec: { ...spec, display }, source: 'display' })}
                    />
                )}
                <Button
                    variant="outline"
                    onClick={() => (simple ? setGalleryOpen(true) : addPanel(newPanel()))}
                    data-attr="dashboard-v2-add-panel"
                >
                    <IconPlus /> Add panel
                </Button>
            </div>
        </div>
    )
}

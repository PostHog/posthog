import { useActions, useValues } from 'kea'
import { createContext, useContext, useMemo, useRef } from 'react'

import { objectsEqual } from 'lib/utils/objects'

import { dashboardV2Logic } from '../dashboard/dashboardV2Logic'
import { parseTimeExpression } from '../dashboard/timeRange'
import { panelEditorLogic } from '../editor/panelEditorLogic'
import type { DashboardV2PanelApi } from '../generated/api.schemas'
import { DashboardV2Panel } from './DashboardV2Panel'
import type { DashboardV2PanelChartProps } from './DashboardV2PanelChart'
import { sampleData } from './sampleData'

const SIX_HOURS_MS = 21_600_000

export const DashboardV2EditablePanelsContext = createContext(false)

function useSampleRange(): { from: number; to: number } {
    const { timeRange } = useValues(dashboardV2Logic)
    const { from, to } = timeRange

    return useMemo(() => {
        const now = new Date()
        const end = parseTimeExpression(to, now, true)?.getTime() ?? now.getTime()
        const start = parseTimeExpression(from, now)?.getTime() ?? end - SIX_HOURS_MS
        return { from: start, to: end }
    }, [from, to])
}

interface DashboardV2SamplePanelProps {
    id: string
    panel: DashboardV2PanelApi
    onEditPanel?: DashboardV2PanelChartProps['onEditPanel']
}

export function DashboardV2SamplePanel({ id, panel, onEditPanel }: DashboardV2SamplePanelProps): JSX.Element {
    const { openPanelId, draft } = useValues(panelEditorLogic)
    const { openPanel, duplicatePanel, confirmRemovePanel } = useActions(panelEditorLogic)
    const editable = useContext(DashboardV2EditablePanelsContext)
    const range = useSampleRange()

    const kept = useRef(panel)
    if (kept.current !== panel && !objectsEqual(kept.current, panel)) {
        kept.current = panel
    }
    const shown = editable && openPanelId === id && draft ? draft : kept.current
    const data = useMemo(() => sampleData(id, shown, range), [id, shown, range])

    return (
        <DashboardV2Panel
            id={editable ? id : undefined}
            panel={shown}
            data={data}
            sample
            onEditPanel={onEditPanel}
            onView={editable ? () => openPanel(id, 'view') : undefined}
            onEdit={editable ? () => openPanel(id, 'edit') : undefined}
            onDuplicate={editable ? () => duplicatePanel(id) : undefined}
            onRemove={editable ? () => confirmRemovePanel(id) : undefined}
        />
    )
}

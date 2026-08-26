import { useValues } from 'kea'

import { lazyWithRetry } from 'lib/utils/retryImport'

import { sidePanelStateLogic } from '../../sidePanelStateLogic'

// Lazy so the side panel registry doesn't pull Max's thread graph (Query, message widgets)
// into the shell chunk. SidePanel already wraps panel content in a Suspense boundary.
const MaxInstance = lazyWithRetry(() => import('scenes/max/Max').then((m) => ({ default: m.MaxInstance })))
const ReportChatSidebar = lazyWithRetry(() =>
    import('products/signals/frontend/v2/components/ReportChatSidebar').then((m) => ({ default: m.ReportChatSidebar }))
)

/** Panel option prefix the inbox v2 demo uses to show its mocked chat instead of the real assistant. */
export const V2_REPORT_PANEL_OPTION = 'v2-report'

export function SidePanelMax(): JSX.Element | null {
    const { selectedTabOptions } = useValues(sidePanelStateLogic)
    const [kind, reportId] = (selectedTabOptions ?? '').split(':')
    if (kind === V2_REPORT_PANEL_OPTION && reportId) {
        return <ReportChatSidebar id={reportId} />
    }
    return <MaxInstance sidePanel />
}

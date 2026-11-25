import { AUTOMATE_PANE } from './todayAutomate'
import { DATA_PANE } from './todayData'
import { MONITOR_PANE } from './todayMonitor'
import type { TodayProductPaneConfig, TodayProductPaneKey } from './todayPaneProducts'

/** In routing order: a page several panes list opens the first of them that is on. */
export const TODAY_PRODUCT_PANES: TodayProductPaneConfig[] = [MONITOR_PANE, AUTOMATE_PANE, DATA_PANE]

export function productPaneConfig(pane: TodayProductPaneKey): TodayProductPaneConfig {
    return { monitor: MONITOR_PANE, automate: AUTOMATE_PANE, data: DATA_PANE }[pane]
}

export function isProductPane(pane: string | null): pane is TodayProductPaneKey {
    return TODAY_PRODUCT_PANES.some((config) => config.pane === pane)
}

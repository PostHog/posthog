import { lazyWithRetry } from 'lib/utils/retryImport'

import { productRailPanes } from '~/products'
import { productScenes } from '~/productScenes'

const sidebars = Object.fromEntries(
    productRailPanes.map((pane) => [
        pane.key,
        lazyWithRetry(async () => {
            const loader = productScenes[pane.sidebarScene as keyof typeof productScenes]
            const module = await loader()
            return { default: module.scene.component }
        }),
    ])
)

export function TodayProductPane({ pane }: { pane: string }): JSX.Element | null {
    const Sidebar = sidebars[pane]
    return Sidebar ? <Sidebar /> : null
}

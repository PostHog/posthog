import { type PreviewPage } from '../types'
import { DashboardPage } from './DashboardPage'
import { EmptyPage } from './EmptyPage'

/** Renders the active preview page from its config. Extend the switch when adding a new page kind. */
export function PreviewPageView({ page }: { page: PreviewPage }): JSX.Element {
    switch (page.kind) {
        case 'dashboard':
            return <DashboardPage metrics={page.metrics} showTrend={page.showTrend} showBars={page.showBars} />
        case 'empty':
            return <EmptyPage title={page.title} subtitle={page.subtitle} />
    }
}

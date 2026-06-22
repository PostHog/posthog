import { type PreviewPage } from '../types'
import { ActivityPage } from './ActivityPage'
import { DashboardPage } from './DashboardPage'
import { EmptyPage } from './EmptyPage'
import { HomePage } from './HomePage'

export function PreviewPageView({ page }: { page: PreviewPage }): JSX.Element {
    switch (page.kind) {
        case 'dashboard':
            return <DashboardPage metrics={page.metrics} charts={page.charts} />
        case 'activity':
            return <ActivityPage events={page.events} />
        case 'empty':
            return <EmptyPage title={page.title} subtitle={page.subtitle} />
        case 'insight':
            return (
                <EmptyPage
                    title={page.title ?? 'Insight'}
                    subtitle={page.subtitle ?? 'Query your data to get started.'}
                />
            )
        case 'home':
            return (
                <HomePage
                    greetingName={page.greetingName}
                    pinnedDashboards={page.pinnedDashboards}
                    recents={page.recents}
                    starred={page.starred}
                />
            )
    }
}

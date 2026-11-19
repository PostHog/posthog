import { ReactNode } from 'react'

import { HomeSectionPlaceholder } from './HomeSectionPlaceholder'

export interface HomeLayoutProps {
    filters: ReactNode
    dashboardLink: ReactNode
    tiles: ReactNode
    showComparison: boolean
    instrumentation: ReactNode
}

export function HomeLayout({
    filters,
    dashboardLink,
    tiles,
    showComparison,
    instrumentation,
}: HomeLayoutProps): JSX.Element {
    return (
        <div className="@container flex min-w-0 flex-col gap-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
                {filters}
                <div className="flex flex-wrap items-center gap-2">
                    {showComparison && (
                        <span className="text-xs text-secondary">Compared with the previous period</span>
                    )}
                    {dashboardLink}
                </div>
            </div>
            {tiles}
            {instrumentation}
            <HomeSectionPlaceholder section="to-review" title="To review" switchLabels={['Sessions', 'Traces']} />
            <HomeSectionPlaceholder section="evals" title="Evals to inspect" />
            <div className="grid grid-cols-1 gap-4 @3xl:grid-cols-2">
                <HomeSectionPlaceholder section="topics" title="Top topics" />
                <HomeSectionPlaceholder section="expensive-users" title="Most expensive users" />
            </div>
        </div>
    )
}

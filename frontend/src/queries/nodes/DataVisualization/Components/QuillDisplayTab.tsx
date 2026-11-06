import { ReactNode } from 'react'

import { ChartOptionSections } from 'lib/components/ChartOptions/ChartOptionSections'
import { displayOptionPages } from 'lib/components/ChartOptions/displayOptionPages'
import { DisplayOptionTab } from 'lib/components/ChartOptions/displayOptions'
import { ChartOptionPage, QuillChartOptionPages } from 'lib/components/ChartOptions/QuillChartOptionPages'

export interface QuillDisplayTabProps {
    tabs: DisplayOptionTab[]
    goalLines: { title: string; count: number; content: ReactNode } | null
}

export function QuillDisplayTab({ tabs, goalLines }: QuillDisplayTabProps): JSX.Element {
    const { home, pages } = displayOptionPages(tabs)
    const optionPages: ChartOptionPage[] = pages.map((page) => ({
        key: page.key,
        title: page.title,
        count: page.count,
        content: <ChartOptionSections sections={page.sections} />,
    }))
    if (goalLines) {
        // Before "More options", which stays last.
        const moreIndex = optionPages.findIndex((page) => page.key === 'more')
        optionPages.splice(moreIndex === -1 ? optionPages.length : moreIndex, 0, { key: 'goals', ...goalLines })
    }

    return (
        <QuillChartOptionPages
            className="p-3"
            data-attr="sql-display-options-panel"
            home={home.length > 0 ? <ChartOptionSections sections={home} /> : null}
            pages={optionPages}
        />
    )
}

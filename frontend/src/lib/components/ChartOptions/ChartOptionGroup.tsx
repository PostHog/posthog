import { ReactNode } from 'react'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { ChartOptionLabel } from './ChartOptionLabel'
import { QuillChartOptionGroup } from './QuillChartOptionGroup'

export interface ChartOptionGroupProps {
    title: string
    info?: string
    children: ReactNode
}

export function ChartOptionGroup(props: ChartOptionGroupProps): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return <QuillChartOptionGroup {...props} />
    }

    const { title, info, children } = props
    return (
        <section className="flex flex-col gap-2">
            <h5 className="m-0 font-semibold">
                <ChartOptionLabel label={title} info={info} />
            </h5>
            {children}
        </section>
    )
}

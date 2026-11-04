import { ReactNode } from 'react'

import { ChartOptionLabel } from './ChartOptionLabel'

export interface ChartOptionGroupProps {
    title: string
    info?: string
    children: ReactNode
}

export function ChartOptionGroup(props: ChartOptionGroupProps): JSX.Element {
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

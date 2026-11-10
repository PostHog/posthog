import { Fragment } from 'react'

import { ChartOptionGroup } from './ChartOptionGroup'
import type { DisplayOptionSection } from './displayOptions'

export function ChartOptionSections({ sections }: { sections: DisplayOptionSection[] }): JSX.Element {
    return (
        <>
            {sections.map((section) => {
                const items = section.items.map((item) => <Fragment key={item.name}>{item.element}</Fragment>)
                return section.title ? (
                    <ChartOptionGroup key={section.key} title={section.title} info={section.tooltip}>
                        {items}
                    </ChartOptionGroup>
                ) : (
                    <Fragment key={section.key}>{items}</Fragment>
                )
            })}
        </>
    )
}

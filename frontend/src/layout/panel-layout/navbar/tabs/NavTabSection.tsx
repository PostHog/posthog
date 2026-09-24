import { ReactNode, useState } from 'react'

import { Collapsible } from 'lib/ui/Collapsible/Collapsible'

export function NavTabSection({
    label,
    collapsedLabel = label,
    children,
    dataAttr,
}: {
    label: string
    collapsedLabel?: string
    children: ReactNode
    dataAttr: string
}): JSX.Element {
    const [open, setOpen] = useState(true)

    return (
        <Collapsible open={open} onOpenChange={setOpen}>
            <Collapsible.Trigger labelClassName="text-xs font-semibold text-secondary normal-case" data-attr={dataAttr}>
                <span>{open ? label : collapsedLabel}</span>
            </Collapsible.Trigger>
            <Collapsible.Panel keepMounted>{children}</Collapsible.Panel>
        </Collapsible>
    )
}

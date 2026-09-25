import { ReactNode, useState } from 'react'

import { Collapsible } from 'lib/ui/Collapsible/Collapsible'

export function NavTabSection({
    label,
    collapsedLabel = label,
    children,
    dataAttr,
    actions,
}: {
    label: string
    collapsedLabel?: string
    children: ReactNode
    dataAttr: string
    actions?: ReactNode
}): JSX.Element {
    const [open, setOpen] = useState(true)

    return (
        <Collapsible open={open} onOpenChange={setOpen} className="border-t first:border-t-0">
            <div className="flex items-center justify-between">
                <Collapsible.Trigger
                    className="min-h-7 rounded hover:bg-fill-button-tertiary-hover focus-visible:bg-fill-button-tertiary-hover pr-2"
                    labelClassName="flex-1 text-xs font-semibold text-secondary normal-case"
                    data-attr={dataAttr}
                >
                    <span>{open ? label : collapsedLabel}</span>
                </Collapsible.Trigger>
                {actions}
            </div>
            <Collapsible.Panel keepMounted>{children}</Collapsible.Panel>
        </Collapsible>
    )
}

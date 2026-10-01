import { ReactNode, useState } from 'react'

import { Collapsible } from 'lib/ui/Collapsible/Collapsible'

export function NavTabSection({
    label,
    children,
    dataAttr,
    actions,
    open: controlledOpen,
    onOpenChange,
}: {
    label: string
    children: ReactNode
    dataAttr: string
    actions?: ReactNode
    /** Controls the section from outside, for example to persist its state. It starts open otherwise. */
    open?: boolean
    onOpenChange?: (open: boolean) => void
}): JSX.Element {
    const [localOpen, setLocalOpen] = useState(true)
    const open = controlledOpen ?? localOpen
    const setOpen = onOpenChange ?? setLocalOpen

    return (
        <Collapsible open={open} onOpenChange={setOpen} className="border-t first:border-t-0">
            <div className="flex items-center justify-between">
                <Collapsible.Trigger
                    className="min-h-7 rounded hover:bg-fill-button-tertiary-hover focus-visible:bg-fill-button-tertiary-hover pr-2"
                    labelClassName="flex-1 text-xs font-semibold text-secondary normal-case"
                    data-attr={dataAttr}
                >
                    <span>{label}</span>
                </Collapsible.Trigger>
                {actions}
            </div>
            <Collapsible.Panel keepMounted>{children}</Collapsible.Panel>
        </Collapsible>
    )
}

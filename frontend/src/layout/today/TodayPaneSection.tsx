import { ReactNode } from 'react'

import { Collapsible, CollapsibleContent, CollapsibleHeader, CollapsibleTrigger, Separator, Text } from '@posthog/quill'

interface TodayPaneSectionProps {
    label: string
    open: boolean
    count: number
    onToggle: () => void
    actions?: JSX.Element | null
    divider?: boolean
    dataAttr: string
    children: ReactNode
}

export function TodayPaneSection({
    label,
    open,
    count,
    onToggle,
    actions,
    divider = false,
    dataAttr,
    children,
}: TodayPaneSectionProps): JSX.Element {
    return (
        <section aria-label={label} className="flex flex-col gap-1">
            {divider && <Separator />}
            <Collapsible variant="folder" open={open} onOpenChange={onToggle}>
                <CollapsibleHeader>
                    <CollapsibleTrigger data-attr={dataAttr}>
                        {label}
                        {!open && count > 0 && (
                            <Text size="xs" variant="muted" render={<span />} className="tabular-nums">
                                {count}
                            </Text>
                        )}
                    </CollapsibleTrigger>
                    {open && actions && <div className="ms-auto flex shrink-0 items-center">{actions}</div>}
                </CollapsibleHeader>
                <CollapsibleContent className="flex flex-col gap-px">{children}</CollapsibleContent>
            </Collapsible>
        </section>
    )
}

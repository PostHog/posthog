import { ReactNode, useState } from 'react'

import { IconCollapse, IconExpand } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

interface FeatureRequestDetailSectionProps {
    icon: ReactNode
    title: string
    children: ReactNode
    meta?: ReactNode
    action?: ReactNode
    collapsible?: boolean
    defaultCollapsed?: boolean
    collapsed?: boolean
    onCollapsedChange?: (collapsed: boolean) => void
    dataAttr?: string
}

export function FeatureRequestDetailSection({
    icon,
    title,
    children,
    meta,
    action,
    collapsible = false,
    defaultCollapsed = false,
    collapsed,
    onCollapsedChange,
    dataAttr,
}: FeatureRequestDetailSectionProps): JSX.Element {
    const [localCollapsed, setLocalCollapsed] = useState(defaultCollapsed)
    const effectiveCollapsed = collapsed ?? localCollapsed
    const setCollapsed = onCollapsedChange ?? setLocalCollapsed
    const open = !collapsible || !effectiveCollapsed
    const header = (
        <div className="flex flex-1 items-center gap-3 min-w-0">
            <div className="flex items-center gap-2 min-w-0">
                <span className="flex shrink-0 items-center text-secondary [&_svg]:size-[0.9375rem]">{icon}</span>
                <span className="truncate text-sm font-semibold text-primary tracking-tight">{title}</span>
            </div>
            <div className="h-px min-w-4 flex-1 bg-border-light" />
            {meta && <div className="shrink-0">{meta}</div>}
        </div>
    )

    return (
        <section className="flex flex-col gap-3">
            <div className="flex items-center gap-3 min-w-0 select-none">
                {collapsible ? (
                    <LemonButton
                        type="tertiary"
                        size="small"
                        fullWidth
                        onClick={() => setCollapsed(!effectiveCollapsed)}
                        aria-expanded={open}
                        sideIcon={open ? <IconCollapse /> : <IconExpand />}
                        className="min-w-0 flex-1 -ml-2 -my-px"
                        data-attr={dataAttr}
                    >
                        {header}
                    </LemonButton>
                ) : (
                    <div className="flex flex-1 items-center min-w-0 py-1">{header}</div>
                )}
                {action && <div className="shrink-0">{action}</div>}
            </div>
            {open && <div>{children}</div>}
        </section>
    )
}

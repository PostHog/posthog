import { Button, Tooltip, TooltipContent, TooltipTrigger, cn } from '@posthog/quill'

import type { LemonTab } from 'lib/lemon-ui/LemonTabs'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

export interface TodaySceneTabsListProps<T extends string | number> {
    tabs: LemonTab<T>[]
    activeKey: T
    onChange?: (key: T) => void
    dataAttr?: string
}

/** The rows do not render `tooltipDocLink` or `completed`. */
export function TodaySceneTabsList<T extends string | number>({
    tabs,
    activeKey,
    onChange,
    dataAttr,
}: TodaySceneTabsListProps<T>): JSX.Element {
    return (
        <nav aria-label="Page sections" data-attr={dataAttr} className="flex flex-col">
            {tabs.map((tab) => {
                const active = tab.key === activeKey
                const disabled = !!tab.disabledReason
                const tooltip = tab.disabledReason || tab.tooltip
                const row = (
                    <Button
                        size="row"
                        left
                        disabled={disabled}
                        aria-current={active ? 'page' : undefined}
                        data-attr={tab['data-attr']}
                        onClick={disabled ? undefined : () => onChange?.(tab.key)}
                        className={cn(
                            'w-full min-w-0 font-semibold text-foreground [&>span]:w-full',
                            active && 'bg-fill-selected'
                        )}
                        {...(tab.link && !disabled
                            ? { nativeButton: false, render: <LinkPrimitive to={tab.link} /> }
                            : {})}
                    >
                        {tab.label}
                    </Button>
                )

                return tooltip ? (
                    <Tooltip key={tab.key}>
                        <TooltipTrigger delay={0} render={<div />}>
                            {row}
                        </TooltipTrigger>
                        <TooltipContent side="right">{tooltip}</TooltipContent>
                    </Tooltip>
                ) : (
                    <div key={tab.key}>{row}</div>
                )
            })}
        </nav>
    )
}

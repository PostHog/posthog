import { useValues } from 'kea'

import { IconEllipsis } from '@posthog/icons'
import { Button, MenuLabel, Popover, PopoverContent, PopoverTrigger, TooltipProvider } from '@posthog/quill'

import { insightLogic } from 'scenes/insights/insightLogic'

import { DisplayOptionsNext, OptionTooltip } from './DisplayOptionsNext'
import { DisplayOptionsSection, useInsightDisplayOptionSections } from './insightDisplayOptions'

function OptionsPopoverContent({ sections }: { sections: DisplayOptionsSection[] }): JSX.Element {
    return (
        <PopoverContent align="end" className="w-72 p-0">
            <TooltipProvider>
                <div className="flex max-h-[70vh] flex-col overflow-y-auto py-1">
                    {sections.map((section) => (
                        <div key={section.key} className="flex flex-col gap-px pb-1">
                            <MenuLabel data-attr={section.dataAttr} className="flex items-center gap-1">
                                {section.title}
                                {section.tooltip && <OptionTooltip>{section.tooltip}</OptionTooltip>}
                            </MenuLabel>
                            {section.items.map((key) => {
                                const Option = DisplayOptionsNext[key]
                                return <Option key={key} />
                            })}
                        </div>
                    ))}
                </div>
            </TooltipProvider>
        </PopoverContent>
    )
}

export function InsightDisplayOptionsMenuNext(): JSX.Element | null {
    const { editingDisabledReason } = useValues(insightLogic)
    const { sections, count } = useInsightDisplayOptionSections()

    const visibleSections = sections.filter((section) => section.items.length > 0)
    if (visibleSections.length === 0) {
        return null
    }

    return (
        <>
            <Popover>
                <PopoverTrigger
                    render={
                        <Button
                            variant="outline"
                            size="sm"
                            data-quill
                            data-attr="insight-display-options"
                            aria-label="Options"
                            className="@max-[780px]:hidden"
                            disabled={!!editingDisabledReason}
                            title={editingDisabledReason ?? undefined}
                        />
                    }
                >
                    <span className="whitespace-nowrap">
                        Options
                        {count ? <span className="ml-0.5 text-muted-foreground ligatures-none">({count})</span> : null}
                    </span>
                </PopoverTrigger>
                <OptionsPopoverContent sections={visibleSections} />
            </Popover>
            <Popover>
                <PopoverTrigger
                    render={
                        <Button
                            variant="outline"
                            size="icon-sm"
                            data-quill
                            data-attr="insight-display-options"
                            aria-label="Options"
                            className="hidden @max-[780px]:flex order-[999]"
                            disabled={!!editingDisabledReason}
                            title={editingDisabledReason ?? undefined}
                        />
                    }
                >
                    <IconEllipsis />
                </PopoverTrigger>
                <OptionsPopoverContent sections={visibleSections} />
            </Popover>
        </>
    )
}

import { IconInfo } from '@posthog/icons'
import { FieldLegend, FieldSet, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import type { ChartOptionGroupProps } from './ChartOptionGroup'

export function QuillChartOptionGroup({ title, info, children }: ChartOptionGroupProps): JSX.Element {
    return (
        <FieldSet className="gap-2">
            <FieldLegend variant="label" className="flex items-center gap-1">
                {title}
                {info && (
                    <Tooltip>
                        <TooltipTrigger render={<span className="inline-flex text-muted-foreground" />}>
                            <IconInfo />
                        </TooltipTrigger>
                        <TooltipContent className="max-w-64">{info}</TooltipContent>
                    </Tooltip>
                )}
            </FieldLegend>
            {children}
        </FieldSet>
    )
}

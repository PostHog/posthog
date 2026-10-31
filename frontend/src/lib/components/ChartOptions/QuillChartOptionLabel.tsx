import { IconInfo } from '@posthog/icons'
import { FieldLabel, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

export interface QuillChartOptionLabelProps {
    htmlFor: string
    label: string
    info?: string
}

export function QuillChartOptionLabel({ htmlFor, label, info }: QuillChartOptionLabelProps): JSX.Element {
    return (
        <FieldLabel htmlFor={htmlFor} className="items-center gap-1 font-normal">
            {label}
            {info && (
                <Tooltip>
                    <TooltipTrigger render={<span className="inline-flex text-muted-foreground" />}>
                        <IconInfo />
                    </TooltipTrigger>
                    <TooltipContent className="max-w-64">{info}</TooltipContent>
                </Tooltip>
            )}
        </FieldLabel>
    )
}

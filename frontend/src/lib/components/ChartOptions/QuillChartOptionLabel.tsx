import { IconInfo } from '@posthog/icons'
import { FieldLabel, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

export interface QuillChartOptionLabelProps {
    htmlFor: string
    label: string
    info?: string
    infoLink?: string
}

export function QuillChartOptionLabel({ htmlFor, label, info, infoLink }: QuillChartOptionLabelProps): JSX.Element {
    return (
        <FieldLabel htmlFor={htmlFor} className="items-center gap-1 font-normal">
            {label}
            {info && (
                <Tooltip>
                    <TooltipTrigger render={<span className="inline-flex text-muted-foreground" />}>
                        <IconInfo />
                    </TooltipTrigger>
                    <TooltipContent className="max-w-64">
                        <div className="flex flex-col gap-1">
                            <span>{info}</span>
                            {infoLink && (
                                <LinkPrimitive
                                    to={infoLink}
                                    target="_blank"
                                    className="text-xs text-primary-on-foreground underline"
                                    data-ph-capture-attribute-autocapture-event-name="clicked tooltip doc link"
                                    data-ph-capture-attribute-doclink={infoLink}
                                >
                                    Read the docs
                                </LinkPrimitive>
                            )}
                        </div>
                    </TooltipContent>
                </Tooltip>
            )}
        </FieldLabel>
    )
}

import { IconPlus, IconX } from '@posthog/icons'
import { Button, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { EventPicker } from './EventPicker'
import { InspectorField } from './InspectorField'

/** An ordered list of events, like a trend's series or a funnel's steps. */
export function EventStepList({
    label,
    itemLabel,
    values,
    min,
    max,
    onChange,
}: {
    label: string
    /** One entry, for example "event" or "step". */
    itemLabel: string
    values: string[]
    min: number
    max: number
    onChange: (values: string[]) => void
}): JSX.Element {
    const seen = new Map<string, number>()
    return (
        <InspectorField label={label}>
            <div className="flex flex-col gap-2">
                {values.map((item, index) => {
                    const count = seen.get(item) ?? 0
                    seen.set(item, count + 1)
                    return (
                        <div key={count ? `${item}#${count}` : item} className="flex items-center gap-2">
                            <Text
                                size="xs"
                                variant="muted"
                                render={<span />}
                                className="w-4 shrink-0 text-center tabular-nums"
                                translate="no"
                            >
                                {index + 1}
                            </Text>
                            <div className="min-w-0 flex-1">
                                <EventPicker
                                    value={item}
                                    onChange={(event) =>
                                        onChange(values.map((current, i) => (i === index ? event : current)))
                                    }
                                />
                            </div>
                            <Tooltip>
                                <TooltipTrigger
                                    delay={0}
                                    render={
                                        <Button
                                            variant="default"
                                            size="icon-sm"
                                            aria-label={`Remove ${itemLabel} ${index + 1}`}
                                            disabled={values.length <= min}
                                            onClick={() => onChange(values.filter((_, i) => i !== index))}
                                        />
                                    }
                                >
                                    <IconX />
                                </TooltipTrigger>
                                <TooltipContent>
                                    {values.length <= min
                                        ? `Keep at least ${min} ${itemLabel}${min === 1 ? '' : 's'}`
                                        : `Remove ${itemLabel}`}
                                </TooltipContent>
                            </Tooltip>
                        </div>
                    )
                })}
                {values.length < max ? (
                    <Button
                        variant="outline"
                        size="sm"
                        className="self-start"
                        onClick={() => onChange([...values, '$pageview'])}
                    >
                        <IconPlus />
                        {`Add ${itemLabel}`}
                    </Button>
                ) : null}
            </div>
        </InspectorField>
    )
}

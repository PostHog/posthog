import { IconPlus, IconX } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { EventPicker } from './EventPicker'
import { InspectorField } from './InspectorField'

/** An ordered list of events, like a trend's series or a funnel's steps. */
export function EventStepList({
    label,
    values,
    min,
    max,
    onChange,
}: {
    label: string
    values: string[]
    min: number
    max: number
    onChange: (values: string[]) => void
}): JSX.Element {
    const seen = new Map<string, number>()
    return (
        <InspectorField label={label}>
            <div className="flex flex-col gap-1.5">
                {values.map((item, index) => {
                    const count = seen.get(item) ?? 0
                    seen.set(item, count + 1)
                    return (
                        <div key={count ? `${item}#${count}` : item} className="flex items-center gap-1.5">
                            <span className="w-4 shrink-0 text-center text-xs tabular-nums text-muted-foreground">
                                {index + 1}
                            </span>
                            <div className="min-w-0 flex-1">
                                <EventPicker
                                    value={item}
                                    onChange={(event) =>
                                        onChange(values.map((current, i) => (i === index ? event : current)))
                                    }
                                />
                            </div>
                            <Button
                                variant="default"
                                size="icon-sm"
                                aria-label="Remove"
                                disabled={values.length <= min}
                                onClick={() => onChange(values.filter((_, i) => i !== index))}
                            >
                                <IconX />
                            </Button>
                        </div>
                    )
                })}
                {values.length < max ? (
                    <Button variant="outline" size="sm" onClick={() => onChange([...values, '$pageview'])}>
                        <IconPlus />
                        Add
                    </Button>
                ) : null}
            </div>
        </InspectorField>
    )
}

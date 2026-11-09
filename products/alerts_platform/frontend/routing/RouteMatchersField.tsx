import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput } from '@posthog/lemon-ui'

import type { AlertRouteMatcherApi } from '../generated/api.schemas'

interface RouteMatchersFieldProps {
    value?: AlertRouteMatcherApi[]
    onChange?: (matchers: AlertRouteMatcherApi[]) => void
}

export function RouteMatchersField({ value = [], onChange }: RouteMatchersFieldProps): JSX.Element {
    const update = (index: number, change: Partial<AlertRouteMatcherApi>): void => {
        onChange?.(value.map((matcher, i) => (i === index ? { ...matcher, ...change } : matcher)))
    }

    return (
        <div className="flex flex-col gap-2">
            {value.length === 0 ? (
                <LemonBanner type="warning">
                    With no conditions, this route matches every alert in the project.
                </LemonBanner>
            ) : (
                value.map((matcher, index) => (
                    <div key={index} className="flex items-center gap-2">
                        <LemonInput
                            className="flex-1 min-w-0"
                            placeholder="Label, such as team"
                            value={matcher.label}
                            onChange={(label) => update(index, { label })}
                            data-attr="platform-alert-route-matcher-label"
                        />
                        <span className="font-mono text-secondary">=</span>
                        <LemonInput
                            className="flex-1 min-w-0"
                            placeholder="Value, such as checkout"
                            value={matcher.value}
                            onChange={(matcherValue) => update(index, { value: matcherValue })}
                            data-attr="platform-alert-route-matcher-value"
                        />
                        <LemonButton
                            icon={<IconTrash />}
                            size="small"
                            tooltip="Remove condition"
                            onClick={() => onChange?.(value.filter((_, i) => i !== index))}
                            data-attr="platform-alert-route-matcher-remove"
                        />
                    </div>
                ))
            )}
            <div>
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconPlus />}
                    onClick={() => onChange?.([...value, { label: '', value: '' }])}
                    data-attr="platform-alert-route-matcher-add"
                >
                    Add condition
                </LemonButton>
            </div>
        </div>
    )
}

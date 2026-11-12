import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import type { RuleMetadataEntry } from './platformAlertFormat'

const COPY = {
    label: { name: 'Name, such as team', value: 'Value, such as checkout' },
    annotation: { name: 'Name, such as runbook_url', value: 'Value, such as https://example.com/runbook' },
}

interface RuleMetadataFieldProps {
    kind: 'label' | 'annotation'
    value?: RuleMetadataEntry[]
    onChange?: (entries: RuleMetadataEntry[]) => void
}

export function RuleMetadataField({ kind, value = [], onChange }: RuleMetadataFieldProps): JSX.Element {
    const update = (index: number, change: Partial<RuleMetadataEntry>): void => {
        onChange?.(value.map((entry, i) => (i === index ? { ...entry, ...change } : entry)))
    }

    return (
        <div className="flex flex-col gap-2">
            {value.map((entry, index) => (
                <div key={index} className="flex items-center gap-2">
                    <LemonInput
                        className="flex-1 min-w-0"
                        placeholder={COPY[kind].name}
                        value={entry.name}
                        onChange={(name) => update(index, { name })}
                        data-attr={`platform-alert-${kind}-name`}
                    />
                    <span className="font-mono text-secondary">=</span>
                    <LemonInput
                        className="flex-1 min-w-0"
                        placeholder={COPY[kind].value}
                        value={entry.value}
                        onChange={(entryValue) => update(index, { value: entryValue })}
                        data-attr={`platform-alert-${kind}-value`}
                    />
                    <LemonButton
                        icon={<IconTrash />}
                        size="small"
                        tooltip={`Remove ${kind}`}
                        onClick={() => onChange?.(value.filter((_, i) => i !== index))}
                        data-attr={`platform-alert-${kind}-remove`}
                    />
                </div>
            ))}
            <div>
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconPlus />}
                    onClick={() => onChange?.([...value, { name: '', value: '' }])}
                    data-attr={`platform-alert-${kind}-add`}
                >
                    {`Add ${kind}`}
                </LemonButton>
            </div>
        </div>
    )
}

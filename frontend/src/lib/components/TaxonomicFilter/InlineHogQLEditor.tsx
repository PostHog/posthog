import { LemonButton } from '@posthog/lemon-ui'
import { HogQLEditor } from 'lib/components/HogQLEditor/HogQLEditor'
import { TaxonomicFilterValue } from 'lib/components/TaxonomicFilter/types'

import { AnyDataNode } from '~/queries/schema'

export interface InlineHogQLEditorProps {
    value?: TaxonomicFilterValue
    onChange: (value: TaxonomicFilterValue, item?: any) => void
    metadataSource?: AnyDataNode
}

const SHORTCUTS = [
    {
        name: 'Hour',
        value: 'toHour(timestamp)',
    },
    {
        name: 'Day of Week',
        value: "multiIf(toDayOfWeek(timestamp) == 1, 'Monday', toDayOfWeek(timestamp) == 2, 'Tuesday', toDayOfWeek(timestamp) == 3, 'Wednesday', toDayOfWeek(timestamp) == 4, 'Thursday', toDayOfWeek(timestamp) == 5, 'Friday', toDayOfWeek(timestamp) == 6, 'Saturday', 'Sunday')",
    },
]

export function InlineHogQLEditor({ value, onChange }: InlineHogQLEditorProps): JSX.Element {
    return (
        <>
            <div className="flex flex-col gap-2 px-2">
                <div className="taxonomic-group-title px-0 ">HogQL expression</div>
                <div className="flex flex-row gap-1 items-baseline">
                    <span className="text-muted-alt mr-1 text-sm">Shortcuts</span>
                    {SHORTCUTS.map(({ name, value }) => (
                        <LemonButton
                            key={name}
                            size="xsmall"
                            onClick={() => onChange(value, {})}
                            tooltip={value}
                            type="secondary"
                        >
                            {name}
                        </LemonButton>
                    ))}
                </div>
                <HogQLEditor
                    onChange={onChange}
                    value={String(value ?? '')}
                    submitText={value ? 'Update HogQL expression' : 'Add HogQL expression'}
                    disableAutoFocus // :TRICKY: No autofocus here. It's controlled in the TaxonomicFilter.
                    hidePlaceholder
                />
            </div>
        </>
    )
}

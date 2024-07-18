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

export function InlineHogQLEditor({ value, onChange, metadataSource }: InlineHogQLEditorProps): JSX.Element {
    return (
        <>
            <div className="flex flex-row gap-4 px-2">
                <div className="flex flex-col gap-1 w-3/5">
                    <div className="taxonomic-group-title px-0">HogQL expression</div>
                    <HogQLEditor
                        onChange={onChange}
                        value={String(value ?? '')}
                        submitText={value ? 'Update HogQL expression' : 'Add HogQL expression'}
                        metadataSource={metadataSource}
                        disableAutoFocus // :TRICKY: No autofocus here. It's controlled in the TaxonomicFilter.
                    />
                </div>
                <div className="flex flex-col gap-1 w-2/5">
                    <h5 className="mt-1 mb-0">Shortcuts</h5>
                    <ul className="space-y-px w-full">
                        {SHORTCUTS.map(({ name, value }) => (
                            <LemonButton
                                key={name}
                                size="small"
                                fullWidth
                                onClick={() => onChange(value, {})}
                                tooltip={value}
                            >
                                {name}
                            </LemonButton>
                        ))}
                    </ul>
                </div>
            </div>
        </>
    )
}

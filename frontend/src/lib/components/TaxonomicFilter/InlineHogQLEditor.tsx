import { TaxonomicFilterValue } from 'lib/components/TaxonomicFilter/types'
import { HogQLEditor } from 'lib/components/HogQLEditor/HogQLEditor'

export interface InlineHogQLEditorProps {
    value?: TaxonomicFilterValue
    onChange: (value: TaxonomicFilterValue) => void
    hogQLTable?: string
}

export function InlineHogQLEditor({ value, onChange, hogQLTable }: InlineHogQLEditorProps): JSX.Element {
    return (
        <div className="px-2">
            <HogQLEditor
                onChange={onChange}
                value={String(value ?? '')}
                hogQLTable={hogQLTable}
                submitText={value ? 'Update HogQL expression' : 'Add HogQL expression'}
                disableAutoFocus // :TRICKY: No autofocus here. It's controlled in the TaxonomicFilter.
            />
        </div>
    )
}

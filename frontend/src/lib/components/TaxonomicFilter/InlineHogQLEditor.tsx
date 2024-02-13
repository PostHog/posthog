import { HogQLEditor } from 'lib/components/HogQLEditor/HogQLEditor'
import { TaxonomicFilterValue } from 'lib/components/TaxonomicFilter/types'

import { AnyDataNode } from '~/queries/schema'

export interface InlineHogQLEditorProps {
    value?: TaxonomicFilterValue
    onChange: (value: TaxonomicFilterValue) => void
    metadataSource?: AnyDataNode
}

export function InlineHogQLEditor({ value, onChange, metadataSource }: InlineHogQLEditorProps): JSX.Element {
    return (
        <div className="px-2">
            <HogQLEditor
                onChange={onChange}
                value={String(value ?? '')}
                metadataSource={metadataSource}
                submitText={value ? 'Update HogQL expression' : 'Add HogQL expression'}
                disableAutoFocus // :TRICKY: No autofocus here. It's controlled in the TaxonomicFilter.
            />
        </div>
    )
}

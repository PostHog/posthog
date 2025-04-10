import { HogQLEditor } from 'lib/components/HogQLEditor/HogQLEditor'
import { TaxonomicFilterValue } from 'lib/components/TaxonomicFilter/types'

import { AnyDataNode } from '~/queries/schema/schema-general'

export interface InlineHogQLEditorProps {
    value?: TaxonomicFilterValue
    onChange: (value: TaxonomicFilterValue, item?: any) => void
    metadataSource?: AnyDataNode
}

export function InlineHogQLEditor({ value, onChange, metadataSource }: InlineHogQLEditorProps): JSX.Element {
    return (
        <>
            <div className="taxonomic-group-title">SQL expression</div>
            <div className="px-2 pt-2">
                <HogQLEditor
                    onChange={onChange}
                    value={String(value ?? '')}
                    metadataSource={metadataSource}
                    submitText={value ? 'Update SQL expression' : 'Add SQL expression'}
                    disableAutoFocus // :TRICKY: No autofocus here. It's controlled in the TaxonomicFilter.
                />
            </div>
        </>
    )
}

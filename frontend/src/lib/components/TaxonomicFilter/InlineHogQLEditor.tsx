import { HogQLEditor } from 'lib/components/HogQLEditor/HogQLEditor'
import { TaxonomicFilterValue } from 'lib/components/TaxonomicFilter/types'
import MaxTool from 'scenes/max/MaxTool'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { AnyDataNode } from '~/queries/schema/schema-general'

export interface InlineHogQLEditorProps {
    value?: TaxonomicFilterValue
    onChange: (value: TaxonomicFilterValue, item?: any) => void
    metadataSource?: AnyDataNode
    globals?: Record<string, any>
    showBreakdownLabelHint?: boolean
}

export function InlineHogQLEditor({
    value,
    onChange,
    metadataSource,
    globals,
    showBreakdownLabelHint,
}: InlineHogQLEditorProps): JSX.Element {
    const currentExpression = String(value ?? '')
    return (
        <>
            <div className="taxonomic-group-title">SQL expression</div>
            <div className="px-2 pt-2">
                <MaxTool
                    identifier="fix_hogql_query"
                    context={{
                        hogql_query: currentExpression,
                        error_message: '',
                    }}
                    contextDescription={{
                        text: 'Current SQL expression',
                        icon: iconForType('data_warehouse'),
                    }}
                    callback={(toolOutput: string) => {
                        if (typeof toolOutput === 'string' && toolOutput.length > 0) {
                            onChange(toolOutput)
                        }
                    }}
                    suggestions={[]}
                    introOverride={{
                        headline: 'What SQL expression do you need?',
                        description: 'Let me help you write or refine a SQL expression.',
                    }}
                >
                    <HogQLEditor
                        onChange={onChange}
                        value={currentExpression}
                        metadataSource={metadataSource}
                        globals={globals}
                        submitText={value ? 'Update SQL expression' : 'Add SQL expression'}
                        showBreakdownLabelHint={showBreakdownLabelHint}
                        disableAutoFocus // :TRICKY: No autofocus here. It's controlled in the TaxonomicFilter.
                    />
                </MaxTool>
            </div>
        </>
    )
}

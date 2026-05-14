import { useValues } from 'kea'

import { HogQLEditor } from 'lib/components/HogQLEditor/HogQLEditor'
import { TaxonomicFilterValue } from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
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
    const { featureFlags } = useValues(featureFlagLogic)
    const aiSnippetEnabled = !!featureFlags[FEATURE_FLAGS.SQL_EXPRESSION_AI_SNIPPET]
    const currentExpression = String(value ?? '')
    const editor = (
        <HogQLEditor
            onChange={onChange}
            value={currentExpression}
            metadataSource={metadataSource}
            globals={globals}
            submitText={value ? 'Update SQL expression' : 'Add SQL expression'}
            showBreakdownLabelHint={showBreakdownLabelHint}
            disableAutoFocus // :TRICKY: No autofocus here. It's controlled in the TaxonomicFilter.
        />
    )
    return (
        <>
            <div className="taxonomic-group-title">SQL expression</div>
            <div className="px-2 pt-2">
                {aiSnippetEnabled ? (
                    <MaxTool
                        identifier="write_hogql_expression"
                        context={{
                            current_expression: currentExpression,
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
                        position="bottom-right"
                    >
                        {editor}
                    </MaxTool>
                ) : (
                    editor
                )}
            </div>
        </>
    )
}

import { useActions, useValues } from 'kea'

import {
    CyclotronJobTemplateSuggestionsButton,
    useTemplateEditorCursor,
} from 'lib/components/CyclotronJob/CyclotronJobTemplateSuggestions'
import {
    insertTemplateReference,
    templateReferenceForOption,
} from 'lib/components/CyclotronJob/cyclotronJobTemplateSuggestionsLogic'
import { CodeEditorInline } from 'lib/monaco/CodeEditorInline'

import { emailTemplaterLogic } from './emailTemplaterLogic'

export function LiquidSupportedText({
    value,
    onChange,
    globals,
}: {
    value: string
    onChange: (value?: string) => void
    globals: any
}): JSX.Element {
    const { templatingEngine } = useValues(emailTemplaterLogic)
    const { setTemplatingEngine } = useActions(emailTemplaterLogic)
    const { onEditorMount, cursorOffset } = useTemplateEditorCursor()

    const templating = templatingEngine ?? 'hog'

    return (
        <span className="flex grow group relative justify-between">
            <span className="absolute top-0 right-2 z-20 p-px opacity-0 transition-opacity group-hover:opacity-100">
                <CyclotronJobTemplateSuggestionsButton
                    templating={templatingEngine}
                    setTemplatingEngine={setTemplatingEngine}
                    value={value}
                    onOptionSelect={(option) => {
                        onChange?.(
                            insertTemplateReference(
                                value || '',
                                templateReferenceForOption(option, templating),
                                cursorOffset()
                            )
                        )
                    }}
                />
            </span>
            <CodeEditorInline
                embedded
                className="flex-1"
                globals={globals}
                value={value}
                language={templating === 'hog' ? 'hogTemplate' : 'liquid'}
                onChange={onChange}
                onMount={onEditorMount}
            />
        </span>
    )
}

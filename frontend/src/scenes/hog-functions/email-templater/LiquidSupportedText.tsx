import clsx from 'clsx'
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
    placeholder,
    plain,
}: {
    value: string
    onChange: (value?: string) => void
    globals: any
    placeholder?: string
    /** Shows the value in the page font, so it reads as a text field rather than code. */
    plain?: boolean
}): JSX.Element {
    const { templatingEngine } = useValues(emailTemplaterLogic)
    const { setTemplatingEngine } = useActions(emailTemplaterLogic)
    const { onEditorMount, cursorOffset } = useTemplateEditorCursor()

    const templating = templatingEngine ?? 'hog'

    const suggestions = (
        <CyclotronJobTemplateSuggestionsButton
            templating={templatingEngine}
            setTemplatingEngine={setTemplatingEngine}
            value={value}
            onOptionSelect={(option) => {
                onChange?.(
                    insertTemplateReference(value || '', templateReferenceForOption(option, templating), cursorOffset())
                )
            }}
        />
    )

    return (
        <span className={clsx('flex grow group relative justify-between', plain && 'items-center gap-1')}>
            {plain ? null : (
                <span className="absolute top-0 right-2 z-20 p-px opacity-0 transition-opacity group-hover:opacity-100">
                    {suggestions}
                </span>
            )}
            {placeholder && !value ? (
                <span
                    className={clsx(
                        'absolute inset-y-0 left-0 flex items-center text-secondary pointer-events-none z-10',
                        !plain && 'pl-2.5'
                    )}
                >
                    {placeholder}
                </span>
            ) : null}
            {/* The code editor always pads its first line by 8px, so a single line moves up to sit in the middle. */}
            <div
                className={clsx(
                    'flex-1 min-w-0',
                    plain &&
                        '-mt-[4.5px] -mb-[4.5px] [&_.margin]:!bg-transparent [&_.monaco-editor]:!bg-transparent [&_.monaco-editor-background]:!bg-transparent'
                )}
            >
                <CodeEditorInline
                    embedded
                    className="flex-1"
                    globals={globals}
                    value={value}
                    language={templating === 'hog' ? 'hogTemplate' : 'liquid'}
                    onChange={onChange}
                    onMount={onEditorMount}
                    allowManualResize={!plain}
                    {...(plain ? { minHeight: '34px', maxHeight: '34px' } : {})}
                    options={
                        plain
                            ? {
                                  fontFamily: getComputedStyle(document.body).fontFamily,
                                  fontSize: 14,
                                  lineHeight: 20,
                                  wordWrap: 'off',
                                  scrollBeyondLastLine: false,
                                  scrollBeyondLastColumn: 0,
                                  lineDecorationsWidth: 0,
                                  glyphMargin: false,
                                  scrollbar: {
                                      vertical: 'hidden',
                                      horizontal: 'hidden',
                                      alwaysConsumeMouseWheel: false,
                                  },
                              }
                            : undefined
                    }
                />
            </div>
            {plain ? (
                <span className="flex shrink-0 items-center opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
                    {suggestions}
                </span>
            ) : null}
        </span>
    )
}

import type { IDisposable, editor } from 'monaco-editor'

import { HogLanguage } from '~/queries/schema/schema-general'

export type TemplateLanguage = HogLanguage.hogTemplate | HogLanguage.liquid

/** How long backspacing has to pause before suggestions reopen. Shorter than this and holding
 * backspace would still fire a backend autocomplete request per repeated keystroke. */
const DELETION_DEBOUNCE_MS = 300

export function isTemplateLanguage(language: string | undefined): language is TemplateLanguage {
    return language === HogLanguage.hogTemplate || language === HogLanguage.liquid
}

/**
 * Whether the cursor sits inside a template expression: `{...}` for hog templates, `{{ ... }}` or
 * `{% ... %}` for liquid. Only text up to the cursor is considered, so an expression the user has
 * not closed yet still counts as open.
 */
export function insideTemplateExpression(textBeforeCursor: string, language: TemplateLanguage): boolean {
    if (language === HogLanguage.liquid) {
        const open = Math.max(textBeforeCursor.lastIndexOf('{{'), textBeforeCursor.lastIndexOf('{%'))
        if (open === -1) {
            return false
        }
        const close = Math.max(textBeforeCursor.lastIndexOf('}}'), textBeforeCursor.lastIndexOf('%}'))
        return close < open
    }
    let depth = 0
    for (let index = 0; index < textBeforeCursor.length; index++) {
        const character = textBeforeCursor[index]
        if (character === '\\') {
            index++
        } else if (depth > 0 && (character === "'" || character === '"')) {
            // Braces inside a string literal are content, not delimiters. Only inside an
            // expression though: in the surrounding prose a lone quote (the apostrophe in
            // "don't") is plain text, not the start of a literal.
            index = skipStringLiteral(textBeforeCursor, index)
        } else if (character === '{') {
            depth++
        } else if (character === '}' && depth > 0) {
            depth--
        }
    }
    return depth > 0
}

/** Returns the index of the closing quote, or the end of the text for an unterminated literal. */
function skipStringLiteral(text: string, openingQuoteIndex: number): number {
    const quote = text[openingQuoteIndex]
    for (let index = openingQuoteIndex + 1; index < text.length; index++) {
        if (text[index] === '\\') {
            index++
        } else if (text[index] === quote) {
            return index
        }
    }
    return text.length
}

/**
 * Monaco closes the suggest widget on backspace and does not reopen it, so a user correcting a
 * chain has to retype a trigger character. Reopen it once the deletions pause, while the cursor is
 * still inside a template expression. Debounced because each reopen costs a backend autocomplete
 * request, and those share the project's query rate limit - one request per pause is fine, one per
 * deleted character is not.
 */
export function retriggerSuggestionsAfterDeletion(editorInstance: editor.IStandaloneCodeEditor): IDisposable {
    let timeout: ReturnType<typeof setTimeout> | null = null

    const cancel = (): void => {
        if (timeout !== null) {
            clearTimeout(timeout)
            timeout = null
        }
    }

    const listener = editorInstance.onDidChangeModelContent((event) => {
        const isDeletion =
            !event.isFlush && event.changes.some((change) => change.text === '' && change.rangeLength > 0)
        // An insertion triggers Monaco's own suggestions, so it also cancels any pending reopen.
        cancel()
        if (!isDeletion) {
            return
        }
        timeout = setTimeout(() => {
            timeout = null
            const model = editorInstance.getModel()
            const position = editorInstance.getPosition()
            if (!model || !position || !editorInstance.hasTextFocus()) {
                return
            }
            // Read the language at fire time: the language selector swaps it on the live
            // model after mount, and a stale language would scan with the wrong rules.
            const languageId = model.getLanguageId()
            if (!isTemplateLanguage(languageId)) {
                return
            }
            if (!insideTemplateExpression(model.getValue().slice(0, model.getOffsetAt(position)), languageId)) {
                return
            }
            editorInstance.trigger('deletionRetrigger', 'editor.action.triggerSuggest', {})
        }, DELETION_DEBOUNCE_MS)
    })

    return {
        dispose: (): void => {
            cancel()
            listener.dispose()
        },
    }
}

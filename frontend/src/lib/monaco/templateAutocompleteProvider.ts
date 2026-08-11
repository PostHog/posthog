import { BuiltLogic } from 'kea'
import { languages } from 'monaco-editor'
import type { IDisposable, editor } from 'monaco-editor'

import { STL } from '@posthog/hogvm'

import type { codeEditorLogicType } from 'lib/monaco/codeEditorLogic'

import { HogLanguage } from '~/queries/schema/schema-general'

/** Languages whose autocomplete is resolved from the globals the frontend already holds. */
export type TemplateLanguage = HogLanguage.hogTemplate | HogLanguage.liquid

interface LiquidFilter {
    name: string
    detail: string
}

const LIQUID_FILTERS: LiquidFilter[] = [
    { name: 'date', detail: 'Format a date or timestamp' },
    { name: 'default', detail: 'Use a fallback when the value is empty' },
    { name: 'join', detail: 'Join a list into a string' },
    { name: 'split', detail: 'Split a string into a list' },
    { name: 'upcase', detail: 'Convert to uppercase' },
    { name: 'downcase', detail: 'Convert to lowercase' },
    { name: 'capitalize', detail: 'Capitalize the first letter' },
    { name: 'replace', detail: 'Replace every match in a string' },
    { name: 'truncate', detail: 'Shorten a string to a length' },
    { name: 'plus', detail: 'Add a number' },
    { name: 'minus', detail: 'Subtract a number' },
]

/** Identifier chain the cursor sits at the end of, e.g. `person.properties.em`. */
const CHAIN_BEFORE_CURSOR = /([A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*\.?)$/
/** A `|` followed by at most the filter name being typed. */
const AFTER_FILTER_PIPE = /\|\s*[A-Za-z0-9_]*$/
const DETAIL_PREVIEW_MAX_LENGTH = 20

export function isTemplateLanguage(language: string | undefined): language is TemplateLanguage {
    return language === HogLanguage.hogTemplate || language === HogLanguage.liquid
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/**
 * Offset at which the template expression containing the cursor starts, or null when the cursor sits
 * in the literal text around it. Only text up to the cursor is considered, so an expression that the
 * user has not closed yet still counts as open.
 */
function expressionStart(textBeforeCursor: string, language: TemplateLanguage): number | null {
    if (language === HogLanguage.liquid) {
        const open = Math.max(textBeforeCursor.lastIndexOf('{{'), textBeforeCursor.lastIndexOf('{%'))
        if (open === -1) {
            return null
        }
        const close = Math.max(textBeforeCursor.lastIndexOf('}}'), textBeforeCursor.lastIndexOf('%}'))
        return close > open ? null : open + 2
    }
    const openOffsets: number[] = []
    for (let index = 0; index < textBeforeCursor.length; index++) {
        const character = textBeforeCursor[index]
        if (character === '\\') {
            index++
        } else if (character === '{') {
            openOffsets.push(index + 1)
        } else if (character === '}') {
            openOffsets.pop()
        }
    }
    return openOffsets.length > 0 ? openOffsets[openOffsets.length - 1] : null
}

/**
 * Keys of the chain that the completed word belongs to. The trailing segment is dropped either way:
 * with a trailing dot it is empty, otherwise it is the partial word Monaco filters on.
 */
function parentChain(expressionTextBeforeCursor: string): string[] {
    const match = CHAIN_BEFORE_CURSOR.exec(expressionTextBeforeCursor)
    if (!match) {
        return []
    }
    const parts = match[1].split('.')
    parts.pop()
    return parts
}

/** The object a chain resolves to within globals, or null when any step is missing or not an object. */
function resolveChain(globals: Record<string, unknown> | undefined, chain: string[]): Record<string, unknown> | null {
    let current: unknown = globals
    for (const key of chain) {
        if (!isPlainObject(current)) {
            return null
        }
        current = current[key]
    }
    return isPlainObject(current) ? current : null
}

/** Type or truncated value shown next to a global, matching what the backend provider returned. */
function globalDetail(value: unknown): string {
    if (Array.isArray(value)) {
        return 'Array'
    }
    if (isPlainObject(value)) {
        return 'Object'
    }
    const serialized = JSON.stringify(value) ?? String(value)
    return serialized.length > DETAIL_PREVIEW_MAX_LENGTH
        ? `${serialized.slice(0, DETAIL_PREVIEW_MAX_LENGTH)}...`
        : serialized
}

/** Mirrors the ordering the backend-backed provider applies, so both feel the same. */
function sortText(kind: languages.CompletionItemKind, label: string): string {
    if (kind === languages.CompletionItemKind.Variable) {
        return `1-${label}`
    }
    if (kind === languages.CompletionItemKind.Function || kind === languages.CompletionItemKind.Method) {
        return `2-${label}`
    }
    return `3-${label}`
}

function globalSuggestions(
    members: Record<string, unknown>,
    kind: languages.CompletionItemKind,
    range: languages.CompletionItem['range']
): languages.CompletionItem[] {
    return Object.entries(members).map(([key, value]) => ({
        label: { label: key, detail: globalDetail(value) },
        insertText: key,
        kind,
        sortText: sortText(kind, key),
        range,
    }))
}

function hogFunctionSuggestions(range: languages.CompletionItem['range']): languages.CompletionItem[] {
    return Object.entries(STL).map(([name, { description }]) => ({
        label: name,
        documentation: description,
        insertText: `${name}()`,
        kind: languages.CompletionItemKind.Function,
        sortText: sortText(languages.CompletionItemKind.Function, name),
        range,
        // Park the cursor between the parentheses we just inserted.
        command: { id: 'cursorLeft', title: 'Move cursor left' },
    }))
}

function liquidFilterSuggestions(range: languages.CompletionItem['range']): languages.CompletionItem[] {
    return LIQUID_FILTERS.map(({ name, detail }) => ({
        label: { label: name, detail },
        insertText: name,
        kind: languages.CompletionItemKind.Function,
        sortText: sortText(languages.CompletionItemKind.Function, name),
        range,
    }))
}

const emptyCompletionList = (): languages.CompletionList => ({ suggestions: [], incomplete: false })

/**
 * Autocomplete for Hog string templates and Liquid. Everything it offers is already in the browser:
 * the globals the editor was handed, plus the Hog standard library. Resolving it here instead of
 * posting a HogQLAutocomplete query keeps each keystroke off the network.
 */
export const templateAutocompleteProvider = (language: TemplateLanguage): languages.CompletionItemProvider => ({
    triggerCharacters: [' ', ',', '.', '{', '|'],
    provideCompletionItems: (model, position) => {
        const logic: BuiltLogic<codeEditorLogicType> | undefined = (model as any).codeEditorLogic
        if (!logic?.isMounted()) {
            return emptyCompletionList()
        }
        const textBeforeCursor = model.getValue().slice(0, model.getOffsetAt(position))
        const start = expressionStart(textBeforeCursor, language)
        if (start === null) {
            return emptyCompletionList()
        }

        const word = model.getWordUntilPosition(position)
        const range: languages.CompletionItem['range'] = {
            startLineNumber: position.lineNumber,
            endLineNumber: position.lineNumber,
            startColumn: word.startColumn,
            endColumn: word.endColumn,
        }
        const expressionText = textBeforeCursor.slice(start)

        if (language === HogLanguage.liquid && AFTER_FILTER_PIPE.test(expressionText)) {
            return { suggestions: liquidFilterSuggestions(range), incomplete: false }
        }

        const globals: Record<string, unknown> | undefined = logic.props.globals
        const chain = parentChain(expressionText)
        const members = resolveChain(globals, chain)

        if (chain.length > 0) {
            return {
                suggestions: members ? globalSuggestions(members, languages.CompletionItemKind.Field, range) : [],
                incomplete: false,
            }
        }
        return {
            suggestions: [
                ...(members ? globalSuggestions(members, languages.CompletionItemKind.Variable, range) : []),
                ...(language === HogLanguage.hogTemplate ? hogFunctionSuggestions(range) : []),
            ],
            incomplete: false,
        }
    },
})

/**
 * Monaco closes the suggest widget on backspace and does not reopen it, so a user who corrects a
 * typo has to retype the trigger character. Reopen it ourselves while the cursor is still inside a
 * template expression. Safe to do per keystroke only because these suggestions never hit the network.
 */
export function retriggerSuggestionsOnDeletion(
    editorInstance: editor.IStandaloneCodeEditor,
    language: TemplateLanguage
): IDisposable {
    return editorInstance.onDidChangeModelContent((event) => {
        if (event.isFlush || !event.changes.some((change) => change.text === '' && change.rangeLength > 0)) {
            return
        }
        if (!editorInstance.hasTextFocus()) {
            return
        }
        const model = editorInstance.getModel()
        const position = editorInstance.getPosition()
        if (!model || !position) {
            return
        }
        if (expressionStart(model.getValue().slice(0, model.getOffsetAt(position)), language) === null) {
            return
        }
        editorInstance.trigger('deleteRetrigger', 'editor.action.triggerSuggest', {})
    })
}

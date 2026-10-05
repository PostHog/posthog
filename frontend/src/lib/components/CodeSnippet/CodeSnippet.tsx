import './CodeSnippet.scss'

import clsx from 'clsx'
import React, { Suspense, lazy, useState } from 'react'

import { IconCollapse, IconCopy, IconExpand } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { retryImport } from 'lib/utils/retryImport'

import { PlainCodeLine } from './PlainCodeLine'

// highlight.js grammars are large, and markdown renders code snippets on pages that every
// logged-in user loads. Show the plain text first and add the highlighting when it arrives.
// Highlighting is cosmetic, so when the chunk cannot load (for example, a stale chunk after a
// deploy) the plain text stays, and no error boundary or page reload runs.
const HighlightedCodeLine = lazy(() =>
    retryImport(() => import('./HighlightedCodeLine'))
        .then((m) => ({ default: m.HighlightedCodeLine }))
        .catch(() => ({ default: PlainCodeLine }))
)

export enum Language {
    Text = 'text',
    Bash = 'bash',
    JSX = 'jsx',
    JavaScript = 'javascript',
    Java = 'java',
    Ruby = 'ruby',
    ObjectiveC = 'objectivec',
    Swift = 'swift',
    Elixir = 'elixir',
    PHP = 'php',
    Python = 'python',
    Dart = 'dart',
    Go = 'go',
    JSON = 'json',
    YAML = 'yaml',
    HTML = 'xml',
    XML = 'xml',
    HTTP = 'http',
    Markup = 'xml',
    SQL = 'sql',
    Kotlin = 'kotlin',
    Groovy = 'groovy',
    CSharp = 'csharp',
    Lua = 'lua',
    VBNet = 'vbnet',
    TypeScript = 'typescript',
    HCL = 'terraform',
    Rust = 'rust',
    C = 'c',
    CPlusPlus = 'cpp',
}

export const getLanguage = (lang: string): Language => {
    switch (lang) {
        case 'bash':
            return Language.Bash
        case 'csharp':
            return Language.CSharp
        case 'javascript':
        case 'jsx':
            return Language.JavaScript
        case 'typescript':
        case 'tsx':
            return Language.TypeScript
        case 'java':
            return Language.Java
        case 'ruby':
            return Language.Ruby
        case 'objectivec':
            return Language.ObjectiveC
        case 'swift':
            return Language.Swift
        case 'elixir':
            return Language.Elixir
        case 'php':
            return Language.PHP
        case 'python':
            return Language.Python
        case 'dart':
            return Language.Dart
        case 'go':
            return Language.Go
        case 'json':
            return Language.JSON
        case 'yaml':
            return Language.YAML
        case 'html':
            return Language.HTML
        case 'xml':
            return Language.XML
        case 'http':
            return Language.HTTP
        case 'markup':
            return Language.Markup
        case 'sql':
            return Language.SQL
        case 'kotlin':
            return Language.Kotlin
        case 'groovy':
            return Language.Groovy
        case 'lua':
        case 'luau':
            return Language.Lua
        case 'vb':
        case 'vbnet':
            return Language.VBNet
        case 'objectivecpp':
            return Language.ObjectiveC
        case 'hcl':
            return Language.HCL
        case 'rust':
            return Language.Rust
        case 'c':
            return Language.C
        case 'cpp':
            return Language.CPlusPlus
        default:
            return Language.Text
    }
}

export interface CodeSnippetProps {
    children: string | undefined | null
    language?: Language
    wrap?: boolean
    compact?: boolean
    actions?: JSX.Element
    className?: string
    /** What is being copied. @example 'link' */
    thing?: string
    /** If set, the snippet becomes expandable when there's more than this number of lines. */
    maxLinesWithoutExpansion?: number
    /**
     * Called after the snippet contents reach the clipboard. Useful for telemetry. Not called when
     * the copy fails, so it is safe to treat as a successful copy.
     */
    onCopy?: () => void
}

export const CodeSnippet = React.memo(function CodeSnippet({
    children: text,
    language = Language.Text,
    wrap = false,
    compact = false,
    className,
    actions,
    thing = 'snippet',
    maxLinesWithoutExpansion,
    onCopy,
}: CodeSnippetProps): JSX.Element | null {
    const [expanded, setExpanded] = useState(false)

    // These all derive from props, so compute them during render rather than mirroring props into
    // state via a useEffect (https://react.dev/learn/you-might-not-need-an-effect).
    const indexOfLimitNewline = maxLinesWithoutExpansion ? indexOfNth(text || '', '\n', maxLinesWithoutExpansion) : -1
    const lineCount = text?.split('\n').length ?? -1
    const displayedText = (indexOfLimitNewline === -1 || expanded ? text : text?.slice(0, indexOfLimitNewline)) ?? ''

    if (lineCount === -1) {
        return null
    }

    return (
        <div className={clsx('CodeSnippet', compact && 'CodeSnippet--compact', className)}>
            <div className="CodeSnippet__actions">
                {actions}
                <LemonButton
                    data-attr="copy-code-button"
                    icon={<IconCopy />}
                    onClick={(e) => {
                        if (text) {
                            e.stopPropagation()
                            // Only report a copy the user actually got: copyToClipboard resolves
                            // false when the clipboard is unavailable (no navigator.clipboard over
                            // plain HTTP) or the write is denied, and callers treat onCopy as
                            // evidence of a successful copy.
                            void copyToClipboard(text, thing).then((copied) => {
                                if (copied) {
                                    onCopy?.()
                                }
                            })
                        }
                    }}
                    size={compact ? 'small' : 'medium'}
                    noPadding
                    tooltip="Copy to clipboard"
                />
            </div>
            <CodeLine text={displayedText} language={language} wrapLines={wrap} />
            {indexOfLimitNewline !== -1 && (
                <LemonButton
                    onClick={() => setExpanded(!expanded)}
                    fullWidth
                    center
                    size="small"
                    type="secondary"
                    icon={expanded ? <IconCollapse /> : <IconExpand />}
                    className="mt-1 mb-0"
                >
                    {expanded
                        ? `Collapse to ${maxLinesWithoutExpansion!} lines`
                        : `Show ${lineCount - maxLinesWithoutExpansion!} more lines`}
                </LemonButton>
            )}
        </div>
    )
})

export function CodeLine({
    text,
    wrapLines,
    language,
}: {
    text: string
    wrapLines: boolean
    language: Language
}): JSX.Element {
    const wrapClassName = wrapLines ? 'whitespace-pre-wrap wrap-anywhere' : undefined

    return (
        <pre className="m-0">
            <Suspense fallback={<PlainCodeLine text={text} className={wrapClassName} />}>
                <HighlightedCodeLine text={text} language={language} className={wrapClassName} />
            </Suspense>
        </pre>
    )
}

function indexOfNth(string: string, character: string, n: number): number {
    let count = 0,
        indexSoFar = 0
    while (count < n) {
        indexSoFar = string.indexOf(character, indexSoFar) + 1
        if (indexSoFar === 0 && count < n) {
            return -1
        }
        count++
    }
    return indexSoFar - 1
}

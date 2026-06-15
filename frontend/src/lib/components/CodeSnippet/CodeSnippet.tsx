import './CodeSnippet.scss'

import clsx from 'clsx'
import { toHtml } from 'hast-util-to-html'
import dart from 'highlight.js/lib/languages/dart'
import elixir from 'highlight.js/lib/languages/elixir'
import groovy from 'highlight.js/lib/languages/groovy'
import http from 'highlight.js/lib/languages/http'
import { useValues } from 'kea'
import { common, createLowlight } from 'lowlight'
import React, { useEffect, useMemo, useState } from 'react'

import { IconCollapse, IconCopy, IconExpand } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import terraform from './terraformLanguage'

// `common` already registers 16 of our 20 languages — only add the missing ones.
const lowlight = createLowlight(common)
lowlight.register({ dart, elixir, groovy, http, terraform })

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
    TypeScript = 'typescript',
    HCL = 'terraform',
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
        case 'hcl':
            return Language.HCL
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
}: CodeSnippetProps): JSX.Element | null {
    const [expanded, setExpanded] = useState(false)
    const [indexOfLimitNewline, setIndexOfLimitNewline] = useState(() =>
        maxLinesWithoutExpansion ? indexOfNth(text || '', '\n', maxLinesWithoutExpansion) : -1
    )
    const [lineCount, setLineCount] = useState(() => text?.split('\n').length || -1)
    const [displayedText, setDisplayedText] = useState(
        () => (indexOfLimitNewline === -1 || expanded ? text : text?.slice(0, indexOfLimitNewline)) ?? ''
    )

    useEffect(() => {
        if (text) {
            setIndexOfLimitNewline(maxLinesWithoutExpansion ? indexOfNth(text, '\n', maxLinesWithoutExpansion) : -1)
            setLineCount(text.split('\n').length)
            setDisplayedText(indexOfLimitNewline === -1 || expanded ? text : text.slice(0, indexOfLimitNewline))
        }
    }, [text, maxLinesWithoutExpansion, expanded]) // oxlint-disable-line react-hooks/exhaustive-deps

    if (lineCount == -1) {
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
                            void copyToClipboard(text, thing)
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
    const { isDarkModeOn } = useValues(themeLogic)

    const highlighted = useMemo(
        () => (lowlight.registered(language) ? lowlight.highlight(language, text) : lowlight.highlightAuto(text)),
        [language, text]
    )
    const style = wrapLines ? ({ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' } as const) : {}

    return (
        <pre className="m-0">
            <code
                className={clsx('hljs', isDarkModeOn && 'hljs-dark')}
                style={style}
                dangerouslySetInnerHTML={{ __html: toHtml(highlighted) }}
            />
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

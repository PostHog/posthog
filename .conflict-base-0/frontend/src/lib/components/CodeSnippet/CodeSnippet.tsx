import './CodeSnippet.scss'

import clsx from 'clsx'
import { useValues } from 'kea'
import React, { type HTMLProps, useEffect, useState } from 'react'
import { PrismAsyncLight as SyntaxHighlighter } from 'react-syntax-highlighter'
import bash from 'react-syntax-highlighter/dist/esm/languages/prism/bash'
import csharp from 'react-syntax-highlighter/dist/esm/languages/prism/csharp'
import dart from 'react-syntax-highlighter/dist/esm/languages/prism/dart'
import elixir from 'react-syntax-highlighter/dist/esm/languages/prism/elixir'
import go from 'react-syntax-highlighter/dist/esm/languages/prism/go'
import groovy from 'react-syntax-highlighter/dist/esm/languages/prism/groovy'
import http from 'react-syntax-highlighter/dist/esm/languages/prism/http'
import java from 'react-syntax-highlighter/dist/esm/languages/prism/java'
import javascript from 'react-syntax-highlighter/dist/esm/languages/prism/javascript'
import json from 'react-syntax-highlighter/dist/esm/languages/prism/json'
import jsx from 'react-syntax-highlighter/dist/esm/languages/prism/jsx'
import kotlin from 'react-syntax-highlighter/dist/esm/languages/prism/kotlin'
import markup from 'react-syntax-highlighter/dist/esm/languages/prism/markup'
import objectiveC from 'react-syntax-highlighter/dist/esm/languages/prism/objectivec'
import php from 'react-syntax-highlighter/dist/esm/languages/prism/php'
import python from 'react-syntax-highlighter/dist/esm/languages/prism/python'
import ruby from 'react-syntax-highlighter/dist/esm/languages/prism/ruby'
import sql from 'react-syntax-highlighter/dist/esm/languages/prism/sql'
import swift from 'react-syntax-highlighter/dist/esm/languages/prism/swift'
import typescript from 'react-syntax-highlighter/dist/esm/languages/prism/typescript'
import yaml from 'react-syntax-highlighter/dist/esm/languages/prism/yaml'

import { IconCollapse, IconCopy, IconExpand } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { darkTheme, lightTheme } from './theme'

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
    HTML = 'html',
    XML = 'xml',
    HTTP = 'http',
    Markup = 'markup',
    SQL = 'sql',
    Kotlin = 'kotlin',
    Groovy = 'groovy',
    CSharp = 'csharp',
    TypeScript = 'typescript',
}

export const getLanguage = (lang: string): Language => {
    switch (lang) {
        case 'bash':
            return Language.Bash
        case 'csharp':
            return Language.CSharp
        case 'jsx':
            return Language.JSX
        case 'javascript':
            return Language.JavaScript
        case 'typescript':
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
        default:
            return Language.Text
    }
}

SyntaxHighlighter.registerLanguage(Language.Bash, bash)
SyntaxHighlighter.registerLanguage(Language.JSX, jsx)
SyntaxHighlighter.registerLanguage(Language.JavaScript, javascript)
SyntaxHighlighter.registerLanguage(Language.Java, java)
SyntaxHighlighter.registerLanguage(Language.Ruby, ruby)
SyntaxHighlighter.registerLanguage(Language.ObjectiveC, objectiveC)
SyntaxHighlighter.registerLanguage(Language.Swift, swift)
SyntaxHighlighter.registerLanguage(Language.Elixir, elixir)
SyntaxHighlighter.registerLanguage(Language.PHP, php)
SyntaxHighlighter.registerLanguage(Language.Python, python)
SyntaxHighlighter.registerLanguage(Language.Dart, dart)
SyntaxHighlighter.registerLanguage(Language.Go, go)
SyntaxHighlighter.registerLanguage(Language.CSharp, csharp)
SyntaxHighlighter.registerLanguage(Language.JSON, json)
SyntaxHighlighter.registerLanguage(Language.YAML, yaml)
SyntaxHighlighter.registerLanguage(Language.HTML, markup)
SyntaxHighlighter.registerLanguage(Language.XML, markup)
SyntaxHighlighter.registerLanguage(Language.Markup, markup)
SyntaxHighlighter.registerLanguage(Language.HTTP, http)
SyntaxHighlighter.registerLanguage(Language.SQL, sql)
SyntaxHighlighter.registerLanguage(Language.Kotlin, kotlin)
SyntaxHighlighter.registerLanguage(Language.TypeScript, typescript)
SyntaxHighlighter.registerLanguage(Language.Groovy, groovy)
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

const syntaxHighlighterLineProps: HTMLProps<HTMLElement> = {
    style: { whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' },
}

function PreTag({ children }: { children: JSX.Element }): JSX.Element {
    return <pre className="m-0">{children}</pre>
}

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

    return (
        <SyntaxHighlighter
            style={isDarkModeOn ? darkTheme : lightTheme}
            language={language}
            wrapLines={wrapLines}
            lineProps={syntaxHighlighterLineProps}
            PreTag={PreTag}
        >
            {text}
        </SyntaxHighlighter>
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

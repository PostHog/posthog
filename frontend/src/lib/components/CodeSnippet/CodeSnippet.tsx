import { PrismAsyncLight as SyntaxHighlighter } from 'react-syntax-highlighter'
import okaidia from 'react-syntax-highlighter/dist/esm/styles/prism/okaidia'
import synthwave84 from 'react-syntax-highlighter/dist/esm/styles/prism/synthwave84'
import bash from 'react-syntax-highlighter/dist/esm/languages/prism/bash'
import jsx from 'react-syntax-highlighter/dist/esm/languages/prism/jsx'
import javascript from 'react-syntax-highlighter/dist/esm/languages/prism/javascript'
import java from 'react-syntax-highlighter/dist/esm/languages/prism/java'
import ruby from 'react-syntax-highlighter/dist/esm/languages/prism/ruby'
import objectiveC from 'react-syntax-highlighter/dist/esm/languages/prism/objectivec'
import swift from 'react-syntax-highlighter/dist/esm/languages/prism/swift'
import elixir from 'react-syntax-highlighter/dist/esm/languages/prism/elixir'
import php from 'react-syntax-highlighter/dist/esm/languages/prism/php'
import python from 'react-syntax-highlighter/dist/esm/languages/prism/python'
import dart from 'react-syntax-highlighter/dist/esm/languages/prism/dart'
import go from 'react-syntax-highlighter/dist/esm/languages/prism/go'
import json from 'react-syntax-highlighter/dist/esm/languages/prism/json'
import yaml from 'react-syntax-highlighter/dist/esm/languages/prism/yaml'
import markup from 'react-syntax-highlighter/dist/esm/languages/prism/markup'
import http from 'react-syntax-highlighter/dist/esm/languages/prism/http'
import sql from 'react-syntax-highlighter/dist/esm/languages/prism/sql'
import { copyToClipboard } from 'lib/utils'
import { Popconfirm } from 'antd'
import { PopconfirmProps } from 'antd/lib/popconfirm'
import './CodeSnippet.scss'
import { IconCopy, IconUnfoldLess, IconUnfoldMore } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { useValues } from 'kea'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { useState } from 'react'
import clsx from 'clsx'

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
SyntaxHighlighter.registerLanguage(Language.JSON, json)
SyntaxHighlighter.registerLanguage(Language.YAML, yaml)
SyntaxHighlighter.registerLanguage(Language.HTML, markup)
SyntaxHighlighter.registerLanguage(Language.XML, markup)
SyntaxHighlighter.registerLanguage(Language.Markup, markup)
SyntaxHighlighter.registerLanguage(Language.HTTP, http)
SyntaxHighlighter.registerLanguage(Language.SQL, sql)

export interface Action {
    icon: React.ReactElement
    title: string
    callback: () => void
    popconfirmProps?: Omit<PopconfirmProps, 'onConfirm'>
}

export interface CodeSnippetProps {
    children: string
    language?: Language
    wrap?: boolean
    compact?: boolean
    actions?: Action[]
    style?: React.CSSProperties
    /** What is being copied. @example 'link' */
    thing?: string
    /** If set, the snippet becomes expandable when there's more than this number of lines. */
    maxLinesWithoutExpansion?: number
}

export function CodeSnippet({
    children: text,
    language = Language.Text,
    wrap = false,
    compact = false,
    style,
    actions,
    thing = 'snippet',
    maxLinesWithoutExpansion,
}: CodeSnippetProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)

    const [expanded, setExpanded] = useState(false)

    const indexOfLimitNewline = maxLinesWithoutExpansion ? indexOfNth(text, '\n', maxLinesWithoutExpansion) : -1
    const displayedText = indexOfLimitNewline === -1 || expanded ? text : text.slice(0, indexOfLimitNewline)

    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div className={clsx('CodeSnippet', compact && 'CodeSnippet--compact')} style={style}>
            <div className="CodeSnippet__actions">
                {actions &&
                    actions.map(({ icon, callback, popconfirmProps, title }, index) =>
                        !popconfirmProps ? (
                            <LemonButton
                                key={`snippet-action-${index}`}
                                onClick={callback}
                                title={title}
                                size={compact ? 'small' : 'medium'}
                            />
                        ) : (
                            <Popconfirm key={`snippet-action-${index}`} {...popconfirmProps} onConfirm={callback}>
                                <LemonButton icon={icon} title={title} size={compact ? 'small' : 'medium'} />
                            </Popconfirm>
                        )
                    )}
                <LemonButton
                    data-attr="copy-code-button"
                    icon={<IconCopy />}
                    onClick={() => {
                        if (text) {
                            void copyToClipboard(text, thing)
                        }
                    }}
                    size={compact ? 'small' : 'medium'}
                />
            </div>
            <SyntaxHighlighter
                style={featureFlags[FEATURE_FLAGS.POSTHOG_3000] ? synthwave84 : okaidia}
                language={language}
                wrapLines={wrap}
                lineProps={{ style: { whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' } }}
            >
                {displayedText}
            </SyntaxHighlighter>
            {indexOfLimitNewline !== -1 && (
                <LemonButton
                    onClick={() => setExpanded(!expanded)}
                    fullWidth
                    center
                    size="small"
                    type="secondary"
                    icon={expanded ? <IconUnfoldLess /> : <IconUnfoldMore />}
                >
                    {expanded ? 'Collapse' : 'Expand'} snippet
                </LemonButton>
            )}
        </div>
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

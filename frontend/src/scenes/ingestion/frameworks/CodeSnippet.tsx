import React from 'react'
import { PrismAsyncLight as SyntaxHighlighter } from 'react-syntax-highlighter'
import okaidia from 'react-syntax-highlighter/dist/esm/styles/prism/okaidia'
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
import { copyToClipboard } from 'lib/utils'
import { Popconfirm } from 'antd'
import { PopconfirmProps } from 'antd/lib/popconfirm'
import './CodeSnippet.scss'
import { IconCopy } from 'lib/components/icons'
import { LemonButton } from 'lib/components/LemonButton'

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

export interface Action {
    icon: React.ReactElement
    title: string
    callback: () => void
    popconfirmProps?: Omit<PopconfirmProps, 'onConfirm'>
}

export interface CodeSnippetProps {
    children?: string
    language?: Language
    wrap?: boolean
    actions?: Action[]
    style?: React.CSSProperties
    copyDescription?: string
    hideCopyButton?: boolean
}

export function CodeSnippet({
    children,
    language = Language.Text,
    wrap = false,
    style,
    actions,
    copyDescription = 'code snippet',
    hideCopyButton = false,
}: CodeSnippetProps): JSX.Element {
    return (
        <div className="CodeSnippet" style={style}>
            <div className="CodeSnippet__actions">
                {actions &&
                    actions.map(({ icon, callback, popconfirmProps, title }, index) =>
                        !popconfirmProps ? (
                            <LemonButton key={`snippet-action-${index}`} onClick={callback} title={title} />
                        ) : (
                            <Popconfirm key={`snippet-action-${index}`} {...popconfirmProps} onConfirm={callback}>
                                <LemonButton icon={icon} title={title} />
                            </Popconfirm>
                        )
                    )}
                {!hideCopyButton && (
                    <LemonButton
                        className="CodeSnippet__copy-button"
                        data-attr="copy-code-button"
                        icon={<IconCopy />}
                        onClick={() => {
                            children && copyToClipboard(children, copyDescription)
                        }}
                    />
                )}
            </div>
            <SyntaxHighlighter
                style={okaidia}
                language={language}
                wrapLines={wrap}
                lineProps={{ style: { whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' } }}
            >
                {children}
            </SyntaxHighlighter>
        </div>
    )
}

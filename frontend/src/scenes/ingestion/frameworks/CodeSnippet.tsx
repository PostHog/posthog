import React from 'react'
import { CopyOutlined } from '@ant-design/icons'
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

export interface Action {
    Icon: any
    title: string
    callback: () => void
    popconfirmProps?: Omit<PopconfirmProps, 'onConfirm'>
}

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
    style = {},
    actions,
    copyDescription = 'code snippet',
    hideCopyButton = false,
}: CodeSnippetProps): JSX.Element {
    return (
        <div className="code-container" style={style}>
            <div className="action-icon-container">
                {actions &&
                    actions.map(({ Icon, callback, popconfirmProps, title }, index) =>
                        !popconfirmProps ? (
                            <Icon
                                key={`snippet-action-${index}`}
                                className="action-icon"
                                onClick={callback}
                                title={title}
                            />
                        ) : (
                            <Popconfirm key={`snippet-action-${index}`} {...popconfirmProps} onConfirm={callback}>
                                <Icon className="action-icon" title={title} />
                            </Popconfirm>
                        )
                    )}
                {!hideCopyButton && (
                    <CopyOutlined
                        className="action-icon"
                        onClick={() => {
                            children && copyToClipboard(children, copyDescription)
                        }}
                        title="Copy"
                    />
                )}
            </div>
            <SyntaxHighlighter
                style={okaidia}
                language={language}
                customStyle={{ borderRadius: 2 }}
                wrapLines={wrap}
                lineProps={{ style: { whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' } }}
            >
                {children}
            </SyntaxHighlighter>
        </div>
    )
}

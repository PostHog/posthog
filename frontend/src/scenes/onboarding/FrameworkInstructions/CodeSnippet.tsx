import React from 'react'
import { toast } from 'react-toastify'
import { CopyOutlined } from '@ant-design/icons'
import { PrismAsyncLight as SyntaxHighlighter } from 'react-syntax-highlighter'
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
SyntaxHighlighter.registerLanguage(Language.HTTP, http)

function copyToClipboard(value: string, description?: string): void {
    const descriptionAdjusted = description ? description.trim() + ' ' : ''
    try {
        navigator.clipboard.writeText(value)
        toast.success(`Copied ${descriptionAdjusted}to clipboard!`)
    } catch (e) {
        toast.error(`Could not copy ${descriptionAdjusted}to clipboard: ${e}`)
    }
}

export function CodeSnippet({
    children,
    language = Language.Text,
    wrap = false,
}: {
    children: string
    language?: Language
    wrap?: boolean
}): JSX.Element {
    return (
        <div className="code-container">
            <CopyOutlined
                className="copy-icon"
                onClick={() => {
                    copyToClipboard(children, 'code snippet')
                }}
            />
            <SyntaxHighlighter
                style={synthwave84}
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

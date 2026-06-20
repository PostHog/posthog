import { memo } from 'react'

import { IconDocument, IconGlobe, IconSearch, IconTerminal } from '@posthog/icons'

import { CodeSnippet } from 'lib/components/CodeSnippet/CodeSnippet'
import { Link } from 'lib/lemon-ui/Link'

import { languageFromPath } from '../../../toolDiffContent'
import type { SandboxToolRendererProps } from '../../sandboxToolRegistry'
import { GenericMcpToolRenderer } from './GenericMcpToolRenderer'
import { SandboxFilePath } from './SandboxFilePath'
import { SandboxToolRow } from './SandboxToolRow'
import {
    MAX_COMMAND_LENGTH,
    MAX_URL_LENGTH,
    getContentImage,
    getContentText,
    getFilename,
    getLineCount,
    getReadToolContent,
    getResultCount,
    stripAnsi,
    stripCodeFences,
    truncateText,
} from './toolContentUtils'
import { ToolContentPre, ToolTitle } from './toolRowPrimitives'
import { resolveToolRowChrome } from './toolRowShared'

function asString(value: unknown): string {
    return typeof value === 'string' ? value : ''
}

function firstLocationPath(props: SandboxToolRendererProps): string | undefined {
    return props.message.locations?.[0]?.path ?? (asString(props.message.rawInput.file_path) || undefined)
}

/** Bash / BashOutput / KillShell — a mono command in the header, ANSI-stripped output in the body. */
const BashToolRenderer = memo(function BashToolRenderer(props: SandboxToolRendererProps): JSX.Element {
    const { message, icon } = props
    const chrome = resolveToolRowChrome(props)
    const command = asString(message.rawInput.command)
    const description = asString(message.rawInput.description)
    const output = stripAnsi(stripCodeFences(getContentText(message.content)))

    return (
        <SandboxToolRow
            icon={icon ?? <IconTerminal />}
            isLoading={chrome.isLoading}
            isFailed={chrome.isFailed}
            wasCancelled={chrome.wasCancelled}
            errorMessage={chrome.errorMessage}
            defaultOpen={chrome.isLoading}
            content={output ? <ToolContentPre>{output}</ToolContentPre> : undefined}
            debugDetails={chrome.debugDetails}
        >
            {description && <ToolTitle>{description}</ToolTitle>}
            {command ? (
                <code
                    title={command}
                    className="font-mono text-[13px] px-1 py-0.5 rounded border border-border bg-fill-secondary text-secondary truncate max-w-full"
                >
                    {truncateText(command, MAX_COMMAND_LENGTH)}
                </code>
            ) : (
                !description && <ToolTitle>{message.title || 'Terminal'}</ToolTitle>
            )}
        </SandboxToolRow>
    )
})

/** Read / NotebookRead — a line/image summary + file chip in the header, file preview in the body. */
const ReadToolRenderer = memo(function ReadToolRenderer(props: SandboxToolRendererProps): JSX.Element {
    const { message, icon } = props
    const chrome = resolveToolRowChrome(props)
    const path = firstLocationPath(props)
    const image = getContentImage(message.content)
    const text = image ? '' : getReadToolContent(message.content)
    const lineCount = getLineCount(text)

    const verb = image
        ? 'Read image'
        : lineCount > 0
          ? `Read ${lineCount} ${lineCount === 1 ? 'line' : 'lines'}`
          : 'Read'

    let content: JSX.Element | undefined
    if (image) {
        content = (
            <img
                src={`data:${image.mimeType};base64,${image.base64}`}
                alt={path ? getFilename(path) : 'Read image'}
                className="max-h-96 max-w-full object-contain rounded bg-surface-secondary p-2"
            />
        )
    } else if (text) {
        content = (
            <CodeSnippet language={languageFromPath(path)} compact maxLinesWithoutExpansion={20}>
                {text}
            </CodeSnippet>
        )
    }

    return (
        <SandboxToolRow
            icon={icon ?? <IconDocument />}
            isLoading={chrome.isLoading}
            isFailed={chrome.isFailed}
            wasCancelled={chrome.wasCancelled}
            errorMessage={chrome.errorMessage}
            content={content}
            debugDetails={chrome.debugDetails}
        >
            <ToolTitle>{path ? `${verb} in` : verb}</ToolTitle>
            {path && <SandboxFilePath path={path} />}
        </SandboxToolRow>
    )
})

/** Grep / Glob / LS — a result count in the header, the matched lines in the body. */
const SearchToolRenderer = memo(function SearchToolRenderer(props: SandboxToolRendererProps): JSX.Element {
    const { message, icon, displayName } = props
    const chrome = resolveToolRowChrome(props)
    const output = getContentText(message.content)
    const count = getResultCount(output)

    return (
        <SandboxToolRow
            icon={icon ?? <IconSearch />}
            isLoading={chrome.isLoading}
            isFailed={chrome.isFailed}
            wasCancelled={chrome.wasCancelled}
            errorMessage={chrome.errorMessage}
            content={output ? <ToolContentPre>{output}</ToolContentPre> : undefined}
            debugDetails={chrome.debugDetails}
        >
            <ToolTitle>{message.title || displayName || 'Search'}</ToolTitle>
            {output && (
                <span className="text-[13px] text-secondary shrink-0">
                    {count} {count === 1 ? 'result' : 'results'}
                </span>
            )}
        </SandboxToolRow>
    )
})

/** WebFetch / WebSearch — a linked URL (or query) in the header, fetched content in the body. */
const FetchToolRenderer = memo(function FetchToolRenderer(props: SandboxToolRendererProps): JSX.Element {
    const { message, icon, displayName } = props
    const chrome = resolveToolRowChrome(props)
    const url = asString(message.rawInput.url)
    const query = asString(message.rawInput.query)
    const output = stripCodeFences(getContentText(message.content))

    return (
        <SandboxToolRow
            icon={icon ?? <IconGlobe />}
            isLoading={chrome.isLoading}
            isFailed={chrome.isFailed}
            wasCancelled={chrome.wasCancelled}
            errorMessage={chrome.errorMessage}
            content={output ? <ToolContentPre>{output}</ToolContentPre> : undefined}
            debugDetails={chrome.debugDetails}
        >
            <ToolTitle>{message.title || displayName || 'Fetch'}</ToolTitle>
            {url ? (
                <Link to={url} target="_blank" title={url} className="text-[13px] font-mono truncate max-w-full">
                    {truncateText(url, MAX_URL_LENGTH)}
                </Link>
            ) : (
                query && (
                    <span className="text-[13px] font-mono text-secondary truncate max-w-full">
                        {truncateText(query, MAX_URL_LENGTH)}
                    </span>
                )
            )}
        </SandboxToolRow>
    )
})

/**
 * Single lazy entry covering every Claude built-in plus the generic MCP fallback — mirrors the agent
 * UI's `ToolCallBlock` dispatch. Switches on the resolved tool name; anything unrecognised renders
 * through `GenericMcpToolRenderer`. Registered for each built-in key and as the registry's default.
 */
export const BuiltinToolRenderer = memo(function BuiltinToolRenderer(props: SandboxToolRendererProps): JSX.Element {
    const name = props.message.claudeToolName ?? props.message.resolvedKey
    switch (name) {
        case 'Bash':
        case 'BashOutput':
        case 'KillShell':
            return <BashToolRenderer {...props} />
        case 'Read':
        case 'NotebookRead':
            return <ReadToolRenderer {...props} />
        case 'Grep':
        case 'Glob':
        case 'LS':
            return <SearchToolRenderer {...props} />
        case 'WebFetch':
        case 'WebSearch':
            return <FetchToolRenderer {...props} />
        default:
            return <GenericMcpToolRenderer {...props} />
    }
})

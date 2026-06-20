import clsx from 'clsx'
import { memo } from 'react'

import { IconDocument, IconGlobe, IconSearch, IconTerminal, IconWrench } from '@posthog/icons'

import { CodeSnippet } from 'lib/components/CodeSnippet/CodeSnippet'
// IconRobot is not exported from @posthog/icons — it lives only in the legacy lib icon set.
import { IconRobot } from 'lib/lemon-ui/icons'

import { languageFromPath } from '../../../toolDiffContent'
import { getPostHogExecDisplay } from '../../posthogExecDisplay'
import type { SandboxToolRendererProps } from '../../sandboxToolRegistry'
import { GenericMcpToolRenderer } from './GenericMcpToolRenderer'
import { SandboxFilePath } from './SandboxFilePath'
import { SandboxToolActivity } from './SandboxToolActivity'
import {
    MAX_COMMAND_LENGTH,
    MAX_URL_LENGTH,
    getCommandOutput,
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
import { ToolOutput } from './ToolOutput'

function asString(value: unknown): string {
    return typeof value === 'string' ? value : ''
}

function firstLocationPath(props: SandboxToolRendererProps): string | undefined {
    return props.message.locations?.[0]?.path ?? (asString(props.message.rawInput.file_path) || undefined)
}

/** Bash / BashOutput / KillShell — command on the second line, ANSI-stripped output in the body. */
const BashToolRenderer = memo(function BashToolRenderer(props: SandboxToolRendererProps): JSX.Element {
    const { message, icon, turnComplete, turnCancelled } = props
    const command = asString(message.rawInput.command)
    const description = asString(message.rawInput.description)
    const output = stripAnsi(stripCodeFences(getCommandOutput(message.content, command, message.rawOutput)))

    return (
        <SandboxToolActivity
            message={message}
            icon={icon ?? <IconTerminal />}
            title={description || message.title || 'Terminal'}
            subtitle={
                command ? (
                    <span className="font-mono" title={command}>
                        {command}
                    </span>
                ) : undefined
            }
            body={output ? <ToolOutput>{output}</ToolOutput> : undefined}
            turnComplete={turnComplete}
            turnCancelled={turnCancelled}
        />
    )
})

/** Read / NotebookRead — line/image summary on line 1, file chip on line 2, preview in the body. */
const ReadToolRenderer = memo(function ReadToolRenderer(props: SandboxToolRendererProps): JSX.Element {
    const { message, icon, turnComplete, turnCancelled } = props
    const path = firstLocationPath(props)
    const image = getContentImage(message.content)
    const text = image ? '' : getReadToolContent(message.content)
    const lineCount = getLineCount(text)

    const title = image
        ? 'Read image'
        : lineCount > 0
          ? `Read ${lineCount} ${lineCount === 1 ? 'line' : 'lines'}`
          : 'Read'

    let body: JSX.Element | undefined
    if (image) {
        body = (
            <img
                src={`data:${image.mimeType};base64,${image.base64}`}
                alt={path ? getFilename(path) : 'Read image'}
                className="max-h-96 max-w-full object-contain rounded bg-surface-secondary p-2"
            />
        )
    } else if (text) {
        body = (
            <CodeSnippet language={languageFromPath(path)} compact maxLinesWithoutExpansion={20}>
                {text}
            </CodeSnippet>
        )
    }

    return (
        <SandboxToolActivity
            message={message}
            icon={icon ?? <IconDocument />}
            title={title}
            subtitle={path ? <SandboxFilePath path={path} /> : undefined}
            body={body}
            turnComplete={turnComplete}
            turnCancelled={turnCancelled}
        />
    )
})

/** Grep / Glob / LS — result count on line 2, matched lines in the body. */
const SearchToolRenderer = memo(function SearchToolRenderer(props: SandboxToolRendererProps): JSX.Element {
    const { message, icon, displayName, turnComplete, turnCancelled } = props
    const output = getContentText(message.content)
    const count = getResultCount(output)

    return (
        <SandboxToolActivity
            message={message}
            icon={icon ?? <IconSearch />}
            title={message.title || displayName || 'Search'}
            subtitle={output ? `${count} ${count === 1 ? 'result' : 'results'}` : undefined}
            body={output ? <ToolOutput>{output}</ToolOutput> : undefined}
            turnComplete={turnComplete}
            turnCancelled={turnCancelled}
        />
    )
})

/**
 * Task / Agent — a delegated subagent run. The header reads `{subagent_type}: {description}`, and the
 * body carries the prompt the subagent was handed plus its returned output. The description lives only
 * in the title (not echoed as a subtitle or input dump), so the card no longer duplicates it.
 */
const SubagentToolRenderer = memo(function SubagentToolRenderer(props: SandboxToolRendererProps): JSX.Element {
    const { message, icon, turnComplete, turnCancelled } = props
    const subagentType = asString(message.rawInput.subagent_type)
    const description = asString(message.rawInput.description) || message.title || ''
    const prompt = asString(message.rawInput.prompt)
    const output = stripCodeFences(getContentText(message.content))
    // An echo-style subagent returns its prompt verbatim — don't render the same text twice.
    const showOutput = !!output && output.trim() !== prompt.trim()

    const title =
        subagentType && description ? `${subagentType}: ${description}` : subagentType || description || 'Subagent'

    const body =
        prompt || showOutput ? (
            <div className="flex flex-col gap-2 min-w-0">
                {prompt && <ToolOutput>{prompt}</ToolOutput>}
                {showOutput && (
                    <div className={clsx('min-w-0', prompt && 'border-t border-border-secondary pt-2')}>
                        <ToolOutput>{output}</ToolOutput>
                    </div>
                )}
            </div>
        ) : undefined

    return (
        <SandboxToolActivity
            message={message}
            icon={icon ?? <IconRobot />}
            title={title}
            body={body}
            turnComplete={turnComplete}
            turnCancelled={turnCancelled}
        />
    )
})

/** WebFetch / WebSearch — linked URL (or query) on line 2, fetched content in the body. */
const FetchToolRenderer = memo(function FetchToolRenderer(props: SandboxToolRendererProps): JSX.Element {
    const { message, icon, turnComplete, turnCancelled } = props
    const url = asString(message.rawInput.url)
    const query = asString(message.rawInput.query)
    const output = stripCodeFences(getContentText(message.content))
    const isSearch = !url && !!query
    // Render the URL as plain mono text — not a highlighted, openable link.
    const target = url || query

    return (
        <SandboxToolActivity
            message={message}
            icon={icon ?? <IconGlobe />}
            title={message.title || (isSearch ? 'Web search' : 'Fetched')}
            subtitle={
                target ? (
                    <span className="font-mono" title={target}>
                        {truncateText(target, MAX_URL_LENGTH)}
                    </span>
                ) : undefined
            }
            body={output ? <ToolOutput>{output}</ToolOutput> : undefined}
            turnComplete={turnComplete}
            turnCancelled={turnCancelled}
        />
    )
})

/**
 * PostHog single-exec discovery verbs (`tools` / `search` / `info` / `schema`, plus the `unknown`
 * fallback). `getPostHogExecDisplay` turns the `command` into a friendly label ("List tools",
 * "Search tools", "Read <tool>", "Inspect <tool>.<field>") and an optional input preview; the
 * discovery output renders in the body. The `call` verb never reaches here — it resolves to its inner
 * tool's renderer instead.
 */
const PostHogExecRenderer = memo(function PostHogExecRenderer(props: SandboxToolRendererProps): JSX.Element {
    const { message, icon, turnComplete, turnCancelled } = props
    const display = getPostHogExecDisplay(message.rawInput)
    const input = display?.input
    const output = stripCodeFences(getContentText(message.content))

    return (
        <SandboxToolActivity
            message={message}
            icon={icon ?? <IconWrench />}
            title={display?.label || message.title || 'Run command'}
            subtitle={
                input ? (
                    <span className="font-mono" title={input}>
                        {truncateText(input, MAX_COMMAND_LENGTH)}
                    </span>
                ) : undefined
            }
            body={output ? <ToolOutput>{output}</ToolOutput> : undefined}
            turnComplete={turnComplete}
            turnCancelled={turnCancelled}
        />
    )
})

/**
 * Single lazy entry covering every Claude built-in plus the generic MCP fallback — mirrors the agent
 * UI's `ToolCallBlock` dispatch. Switches on the resolved tool name; anything unrecognised renders
 * through `GenericMcpToolRenderer`. Registered for each built-in key and as the registry's default.
 */
export const BuiltinToolRenderer = memo(function BuiltinToolRenderer(props: SandboxToolRendererProps): JSX.Element {
    if (props.message.resolvedKey.startsWith('__posthog_exec_')) {
        return <PostHogExecRenderer {...props} />
    }
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
        case 'Task':
        case 'Agent':
            return <SubagentToolRenderer {...props} />
        case 'WebFetch':
        case 'WebSearch':
            return <FetchToolRenderer {...props} />
        default:
            return <GenericMcpToolRenderer {...props} />
    }
})

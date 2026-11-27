import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { IconCheckCircle, IconInfo, IconWarning } from '@posthog/icons'
import { Collapsible, CollapsibleContent, CollapsibleTrigger, Spinner } from '@posthog/quill'

import { isShellTool } from './eventEntries'
import { TranscriptEntry } from './transcriptEntries'

const RESULT_PREVIEW_LENGTH = 180

function ToolStatusIcon({ status }: { status: TranscriptEntry['status'] }): JSX.Element {
    if (status === 'running') {
        return <Spinner className="motion-reduce:animate-none" aria-hidden="true" />
    }
    const Icon = status === 'failed' ? IconWarning : status === 'passed' ? IconCheckCircle : IconInfo
    return <Icon aria-hidden="true" />
}

function TranscriptMarkdown({ text }: { text: string }): JSX.Element {
    // react-markdown escapes raw HTML, so customer content cannot inject markup into the staff page.
    return (
        <div className="transcript-markdown">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
        </div>
    )
}

/** One step of an agent session: a message, thinking, or a tool call with its result. */
export function TranscriptRow({ entry }: { entry: TranscriptEntry }): JSX.Element {
    const tool = entry.kind === 'tool' || entry.kind === 'web'
    const shell = isShellTool(entry)
    const statusLabel = `${shell ? 'Shell call' : 'Tool'} ${entry.status ?? 'status unavailable'}`
    const exitStatus = shell && entry.exitCode !== undefined ? ` · Exit code ${entry.exitCode}` : ''

    return (
        <article className={`transcript-row transcript-${entry.kind}`}>
            <span className="transcript-sequence">{entry.sequence || ''}</span>
            {tool ? (
                <div>
                    <div className="tool-command">
                        <span
                            className={`tool-state ${entry.status ?? ''}`}
                            title={statusLabel + exitStatus}
                            role="img"
                            aria-label={statusLabel + exitStatus}
                        >
                            <ToolStatusIcon status={entry.status} />
                        </span>
                        <strong>{entry.title}</strong>
                        <code>{entry.text}</code>
                    </div>
                    {entry.output ? (
                        <Collapsible className="tool-output">
                            <CollapsibleTrigger>
                                <span className={`tool-result-status ${entry.status ?? ''}`}>
                                    {shell
                                        ? `${statusLabel}${exitStatus} · Result`
                                        : entry.status === 'failed'
                                          ? 'Failed'
                                          : 'Result'}
                                </span>{' '}
                                {entry.output.replaceAll(/\s+/g, ' ').slice(0, RESULT_PREVIEW_LENGTH)}
                            </CollapsibleTrigger>
                            <CollapsibleContent>
                                <pre>{entry.output}</pre>
                            </CollapsibleContent>
                        </Collapsible>
                    ) : (
                        <span className="tool-pending">
                            {entry.status === 'failed' ? 'Failed · No output' : 'No output'}
                        </span>
                    )}
                </div>
            ) : entry.kind === 'thinking' ? (
                <Collapsible className="thinking-block">
                    <CollapsibleTrigger>Thinking…</CollapsibleTrigger>
                    <CollapsibleContent>
                        <TranscriptMarkdown text={entry.text} />
                    </CollapsibleContent>
                </Collapsible>
            ) : entry.kind === 'system' ? (
                <p className="transcript-system">
                    {entry.title && <strong>{entry.title} </strong>}
                    <span>{entry.text}</span>
                </p>
            ) : (
                <TranscriptMarkdown text={entry.text} />
            )}
        </article>
    )
}

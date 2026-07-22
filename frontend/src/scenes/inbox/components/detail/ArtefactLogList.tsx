import { useValues } from 'kea'
import { useState } from 'react'

import { IconChevronDown, IconChevronRight, IconExternal } from '@posthog/icons'
import { LemonTag, Link } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { capitalizeFirstLetter } from 'lib/utils/strings'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { Task } from 'products/posthog_ai/frontend/types/taskTypes'

import { EnrichedReviewer, SignalReportActionability, SignalReportPriority, SignalReportArtefact } from '../../types'
import { SignalReportActionabilityBadge } from '../badges/SignalReportActionabilityBadge'
import { SignalReportPriorityBadge } from '../badges/SignalReportPriorityBadge'
import { ArtefactCommit } from './ArtefactCommit'
import { ArtefactTaskRun } from './ArtefactTaskRun'
import {
    artefactAttributionLabel,
    artefactLocationLabel,
    artefactTypeLabel,
    CodeReferenceContent,
    CommitContent,
    DismissalContent,
    LineReferenceContent,
    NoteContent,
    SignalFindingContent,
    SummaryChangeContent,
    TaskRunArtefactContent,
    TitleChangeContent,
} from './artefactTypes'

/** Map a file extension to a CodeSnippet language for syntax highlighting; falls back to plain text. */
function languageFromPath(path: string | undefined): Language {
    const ext = path?.split('.').pop()?.toLowerCase()
    switch (ext) {
        case 'ts':
        case 'tsx':
            return Language.TypeScript
        case 'js':
        case 'jsx':
        case 'mjs':
        case 'cjs':
            return Language.JavaScript
        case 'py':
            return Language.Python
        case 'go':
            return Language.Go
        case 'rb':
            return Language.Ruby
        case 'java':
            return Language.Java
        case 'kt':
            return Language.Kotlin
        case 'php':
            return Language.PHP
        case 'cs':
            return Language.CSharp
        case 'swift':
            return Language.Swift
        case 'sql':
            return Language.SQL
        case 'json':
            return Language.JSON
        case 'yaml':
        case 'yml':
            return Language.YAML
        case 'sh':
        case 'bash':
            return Language.Bash
        case 'html':
        case 'xml':
            return Language.XML
        default:
            return Language.Text
    }
}

/** Replace dashes/underscores with spaces and capitalize — for enum-ish strings (dismissal reasons). */
function prettify(value: string): string {
    return capitalizeFirstLetter(value.replace(/[-_]/g, ' '))
}

/** Friendly labels for known dismissal reason codes; unknown values fall back to a humanized form. */
const DISMISS_REASON_LABELS: Record<string, string> = {
    slack_dismiss: 'Dismissed from Slack',
}

function dismissReasonLabel(reason: string): string {
    return DISMISS_REASON_LABELS[reason] ?? prettify(reason)
}

/** A short relevance / context note above a code block. */
function RelevanceNote({ note }: { note?: string }): JSX.Element | null {
    if (!note?.trim()) {
        return null
    }
    return <span className="block text-secondary text-xs">{note}</span>
}

/** A read-only highlighted code block sized for the activity log. */
function CodeRefBlock({ code, language }: { code: string; language: Language }): JSX.Element {
    return (
        <div className="mt-1.5">
            <CodeSnippet language={language} compact wrap>
                {code}
            </CodeSnippet>
        </div>
    )
}

/** Judgment rationale, hidden behind a "Show reasoning" toggle. */
function CollapsibleReasoning({ text }: { text: string }): JSX.Element {
    const [expanded, setExpanded] = useState(false)
    return (
        <div className="flex flex-col gap-1">
            <button
                type="button"
                onClick={() => setExpanded((v) => !v)}
                className="flex w-fit items-center gap-1 rounded px-1 py-0.5 text-xs text-secondary transition-colors hover:bg-fill-highlight-50"
            >
                {expanded ? <IconChevronDown /> : <IconChevronRight />}
                {expanded ? 'Hide reasoning' : 'Show reasoning'}
            </button>
            {expanded ? <span className="text-secondary text-xs">{text}</span> : null}
        </div>
    )
}

/** A `note` artefact: a one-line preview that expands to the full markdown body. */
function CollapsibleNote({ note, author }: { note: string; author?: string }): JSX.Element {
    const [expanded, setExpanded] = useState(false)
    const preview = note.split('\n').find((line) => line.trim()) ?? note
    return (
        <div className="flex w-full min-w-0 flex-col gap-1">
            <button
                type="button"
                onClick={() => setExpanded((v) => !v)}
                className="flex w-full min-w-0 items-center gap-1 rounded px-1 py-0.5 text-left text-xs text-secondary transition-colors hover:bg-fill-highlight-50"
            >
                {expanded ? <IconChevronDown className="shrink-0" /> : <IconChevronRight className="shrink-0" />}
                <span className="truncate">{expanded ? 'Hide note' : preview}</span>
            </button>
            {expanded ? (
                <div className="min-w-0">
                    <LemonMarkdown className="text-xs text-secondary leading-normal" disableImages>
                        {note}
                    </LemonMarkdown>
                    {author?.trim() ? <span className="mt-1 block text-tertiary text-[11px]">— {author}</span> : null}
                </div>
            ) : null}
        </div>
    )
}

/**
 * A `title_change` / `summary_change` artefact: shows the value the report now carries, with the
 * previous value tucked behind a "Show previous" toggle (omitted when the field had no prior value).
 * `markdown` renders the body as markdown — summaries are descriptions, titles are plain text.
 * `collapse` hides the new value behind a one-line preview (summaries can be long; titles are short
 * enough to show inline).
 */
function ContentChangeBody({
    previous,
    current,
    markdown = false,
    collapse = false,
}: {
    previous?: string | null
    current: string
    markdown?: boolean
    collapse?: boolean
}): JSX.Element {
    const [expanded, setExpanded] = useState(false)
    const [showPrevious, setShowPrevious] = useState(false)
    const renderText = (text: string, muted: boolean): JSX.Element => {
        const color = muted ? 'text-secondary' : 'text-default'
        return markdown ? (
            <LemonMarkdown className={`text-xs leading-normal ${color}`} disableImages>
                {text}
            </LemonMarkdown>
        ) : (
            <span className={`text-xs ${color}`}>{text}</span>
        )
    }
    const previousToggle = previous?.trim() ? (
        <>
            <button
                type="button"
                onClick={() => setShowPrevious((v) => !v)}
                className="flex w-fit items-center gap-1 rounded px-1 py-0.5 text-xs text-secondary transition-colors hover:bg-fill-highlight-50"
            >
                {showPrevious ? <IconChevronDown /> : <IconChevronRight />}
                {showPrevious ? 'Hide previous' : 'Show previous'}
            </button>
            {showPrevious ? <div className="min-w-0">{renderText(previous, true)}</div> : null}
        </>
    ) : null

    if (collapse) {
        const preview = current.split('\n').find((line) => line.trim()) ?? current
        return (
            <div className="flex w-full min-w-0 flex-col gap-1">
                <button
                    type="button"
                    onClick={() => setExpanded((v) => !v)}
                    className="flex w-full min-w-0 items-center gap-1 rounded px-1 py-0.5 text-left text-xs text-secondary transition-colors hover:bg-fill-highlight-50"
                >
                    {expanded ? <IconChevronDown className="shrink-0" /> : <IconChevronRight className="shrink-0" />}
                    <span className="truncate">{expanded ? 'Hide new value' : preview}</span>
                </button>
                {expanded ? (
                    <>
                        <div className="min-w-0">{renderText(current, false)}</div>
                        {previousToggle}
                    </>
                ) : null}
            </div>
        )
    }

    return (
        <div className="flex w-full min-w-0 flex-col gap-1">
            <div className="min-w-0">{renderText(current, false)}</div>
            {previousToggle}
        </div>
    )
}

/** The suggested-reviewers list as a point-in-time log entry. */
function ReviewersBody({ reviewers }: { reviewers: EnrichedReviewer[] }): JSX.Element {
    if (reviewers.length === 0) {
        return <span className="text-tertiary text-xs">No reviewers assigned.</span>
    }
    return (
        <div className="flex flex-col gap-1">
            {reviewers.map((reviewer) => {
                const name = reviewer.user?.first_name || reviewer.github_name || reviewer.github_login
                return (
                    <div key={reviewer.github_login} className="flex items-center gap-2 text-xs">
                        <img
                            src={`https://github.com/${reviewer.github_login}.png?size=28`}
                            alt=""
                            loading="lazy"
                            className="size-[18px] shrink-0 rounded-full bg-fill-highlight-50"
                        />
                        <span className="truncate text-default">{name}</span>
                        <Link
                            to={`https://github.com/${reviewer.github_login}`}
                            target="_blank"
                            disableClientSideRouting
                            className="ml-auto flex shrink-0 items-center gap-0.5 font-mono text-tertiary text-[11px]"
                        >
                            @{reviewer.github_login}
                            <IconExternal />
                        </Link>
                    </div>
                )
            })}
        </div>
    )
}

/** Per-type body for one artefact row. Content is read defensively — legacy rows may lack fields. */
function ArtefactBody({
    reportId,
    artefact,
    knownTasks,
}: {
    reportId: string
    artefact: SignalReportArtefact
    knownTasks?: Map<string, Task>
}): JSX.Element {
    const content = artefact.content

    switch (artefact.type) {
        case 'code_reference': {
            const c = content as CodeReferenceContent
            return (
                <div>
                    <RelevanceNote note={c.relevance_note} />
                    {c.contents ? <CodeRefBlock code={c.contents} language={languageFromPath(c.file_path)} /> : null}
                </div>
            )
        }
        case 'line_reference': {
            const c = content as LineReferenceContent
            return (
                <div>
                    <RelevanceNote note={c.note} />
                    {c.contents ? <CodeRefBlock code={c.contents} language={languageFromPath(c.file_path)} /> : null}
                </div>
            )
        }
        case 'commit':
            return <ArtefactCommit reportId={reportId} artefactId={artefact.id} content={content as CommitContent} />
        case 'task_run': {
            const c = content as TaskRunArtefactContent
            return <ArtefactTaskRun content={c} knownTask={knownTasks?.get(c.task_id) ?? null} />
        }
        case 'note': {
            const c = content as NoteContent
            return <CollapsibleNote note={c.note} author={c.author} />
        }
        case 'priority_judgment': {
            const c = content as { priority?: SignalReportPriority; explanation?: string }
            return (
                <div className="flex flex-col gap-1">
                    <SignalReportPriorityBadge priority={c.priority} />
                    {c.explanation ? <CollapsibleReasoning text={c.explanation} /> : null}
                </div>
            )
        }
        case 'actionability_judgment': {
            const c = content as {
                actionability?: SignalReportActionability
                already_addressed?: boolean
                explanation?: string
            }
            return (
                <div className="flex flex-col gap-1">
                    <div className="flex items-center gap-2 flex-wrap">
                        <SignalReportActionabilityBadge actionability={c.actionability} />
                        {c.already_addressed ? (
                            <LemonTag size="small" type="warning">
                                Already addressed
                            </LemonTag>
                        ) : null}
                    </div>
                    {c.explanation ? <CollapsibleReasoning text={c.explanation} /> : null}
                </div>
            )
        }
        case 'safety_judgment': {
            const c = content as { choice?: boolean; explanation?: string }
            return (
                <div className="flex flex-col gap-1">
                    <LemonTag size="small" type={c.choice ? 'success' : 'danger'}>
                        {c.choice ? 'Safe to act on' : 'Unsafe'}
                    </LemonTag>
                    {c.explanation ? <CollapsibleReasoning text={c.explanation} /> : null}
                </div>
            )
        }
        case 'signal_finding': {
            const c = content as SignalFindingContent
            const paths = c.relevant_code_paths ?? []
            return (
                <div className="flex flex-col gap-1">
                    <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-mono text-tertiary text-[11px]">{c.signal_id}</span>
                        <LemonTag size="small" type={c.verified ? 'success' : 'muted'}>
                            {c.verified ? 'Verified' : 'Unverified'}
                        </LemonTag>
                    </div>
                    {paths.length > 0 ? (
                        <div className="flex flex-col">
                            {paths.map((path) => (
                                <span key={path} className="truncate font-mono text-secondary text-[11px]">
                                    {path}
                                </span>
                            ))}
                        </div>
                    ) : null}
                </div>
            )
        }
        case 'suggested_reviewers':
            return <ReviewersBody reviewers={(content as unknown as EnrichedReviewer[]) ?? []} />
        case 'title_change': {
            const c = content as TitleChangeContent
            return <ContentChangeBody previous={c.old_title} current={c.new_title ?? ''} />
        }
        case 'summary_change': {
            const c = content as SummaryChangeContent
            return <ContentChangeBody previous={c.old_summary} current={c.new_summary ?? ''} markdown collapse />
        }
        case 'dismissal': {
            const c = content as DismissalContent
            return (
                <div className="flex flex-col gap-1">
                    {c.reason ? (
                        <LemonTag size="small" type="muted">
                            {dismissReasonLabel(c.reason)}
                        </LemonTag>
                    ) : null}
                    {c.note ? <RelevanceNote note={c.note} /> : null}
                </div>
            )
        }
        default: {
            const preview = typeof (content as { content?: unknown })?.content === 'string'
            return <span className="text-tertiary text-xs">{preview ? String((content as any).content) : ''}</span>
        }
    }
}

/** One log row: a header (type · location · attribution · timestamp) over the per-type body. */
function ArtefactRow({
    reportId,
    artefact,
    knownTasks,
}: {
    reportId: string
    artefact: SignalReportArtefact
    knownTasks?: Map<string, Task>
}): JSX.Element {
    const { isDev } = useValues(preflightLogic)
    const [showRaw, setShowRaw] = useState(false)
    const location = artefactLocationLabel(artefact)
    const attribution = artefactAttributionLabel(artefact)

    return (
        <div className="rounded border border-primary bg-surface-primary p-3">
            <div className="mb-1.5 flex items-center gap-2 min-w-0">
                <span className="shrink-0 font-semibold text-xs text-default">{artefactTypeLabel(artefact.type)}</span>
                {location ? <span className="truncate font-mono text-tertiary text-[11px]">{location}</span> : null}
                <div className="ml-auto flex shrink-0 items-center gap-2">
                    {attribution ? <span className="text-tertiary text-[11px]">by {attribution}</span> : null}
                    {isDev ? (
                        <button
                            type="button"
                            onClick={() => setShowRaw((v) => !v)}
                            className="rounded px-1 font-mono text-tertiary text-[11px] transition-colors hover:bg-fill-highlight-50"
                            title="Toggle raw JSON (dev only)"
                        >
                            {'{ }'}
                        </button>
                    ) : null}
                    <TZLabel time={artefact.created_at} className="text-tertiary text-[11px]" />
                </div>
            </div>
            <ArtefactBody reportId={reportId} artefact={artefact} knownTasks={knownTasks} />
            {isDev && showRaw ? (
                <pre className="mt-2 max-h-72 overflow-auto rounded bg-fill-highlight-50 p-2 text-[10px] leading-tight">
                    {JSON.stringify(artefact, null, 2)}
                </pre>
            ) : null}
        </div>
    )
}

/**
 * The report's work-log: every artefact rendered chronologically with a tailored body — judgments,
 * findings, code references, diffs, commits, task runs, notes, and reviewers. Mirrors desktop
 * `ArtefactLogList`. Returns null when there are no artefacts.
 */
export function ArtefactLogList({
    reportId,
    artefacts,
    knownTasks,
}: {
    reportId: string
    artefacts: SignalReportArtefact[]
    /** Tasks the detail logic already resolved, keyed by id — `task_run` rows reuse these instead of refetching. */
    knownTasks?: Map<string, Task>
}): JSX.Element | null {
    if (artefacts.length === 0) {
        return null
    }
    const ordered = [...artefacts].sort((a, b) => a.created_at.localeCompare(b.created_at))
    return (
        <div className="flex flex-col gap-2">
            {ordered.map((artefact) => (
                <ArtefactRow key={artefact.id} reportId={reportId} artefact={artefact} knownTasks={knownTasks} />
            ))}
        </div>
    )
}

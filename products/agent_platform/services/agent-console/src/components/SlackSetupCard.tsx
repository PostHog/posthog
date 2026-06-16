/**
 * `<SlackSetupCard>` — deterministic Slack app setup for a slack-triggered agent.
 *
 * Renders the manifest the backend derives from the agent's slack trigger +
 * tools (scopes + event subscriptions computed, not hand-picked), the
 * "create from manifest" deep link, the live request URLs, and the reminders
 * the manifest can't enforce. The whole point: the user pastes one doc instead
 * of clicking through scopes + event subscriptions and getting them wrong.
 *
 * Surfaced under the slack trigger's detail in the config explorer.
 */

'use client'

import { CheckIcon, CopyIcon, ExternalLinkIcon, MessageSquareIcon } from 'lucide-react'
import { useState } from 'react'

import { getSlackManifest } from '@/lib/apiClient'
import { useResource } from '@/lib/useResource'

export function SlackSetupCard({
    teamId,
    agentSlug,
    revisionId,
}: {
    teamId: number
    agentSlug: string
    revisionId: string
}): React.ReactElement {
    const manifestRes = useResource(
        () => getSlackManifest(teamId, agentSlug, revisionId),
        [teamId, agentSlug, revisionId]
    )
    const data = manifestRes.data
    const manifestJson = data ? JSON.stringify(data.manifest, null, 2) : ''

    return (
        <section>
            <div className="flex items-center gap-2 border-b border-border bg-muted/10 px-4 py-1.5 text-[0.625rem] uppercase tracking-wide text-muted-foreground">
                <MessageSquareIcon className="h-3.5 w-3.5" />
                Slack app setup
            </div>
            {manifestRes.loading && !data ? (
                <p className="px-4 py-3 text-xs text-muted-foreground">Generating manifest…</p>
            ) : manifestRes.error ? (
                <p className="px-4 py-3 text-xs text-muted-foreground">
                    Could not generate the Slack manifest: {manifestRes.error.message}
                </p>
            ) : data ? (
                <div className="space-y-3 px-4 py-3">
                    <p className="text-[0.6875rem] text-muted-foreground">
                        Paste this manifest into Slack to create the app with the right scopes and event subscriptions
                        already filled in — derived from this agent's trigger config and tools.
                    </p>
                    <div className="flex flex-wrap items-center gap-2">
                        <a
                            href="https://api.slack.com/apps?new_app=1"
                            target="_blank"
                            rel="noreferrer"
                            className="inline-flex h-7 items-center gap-1.5 rounded-md bg-primary px-2.5 text-[0.6875rem] font-medium text-primary-foreground transition-opacity hover:opacity-90"
                        >
                            <ExternalLinkIcon className="h-3 w-3" />
                            Create Slack app from manifest
                        </a>
                        <CopyButton text={manifestJson} label="Copy manifest" />
                    </div>
                    <p className="text-[0.6875rem] text-muted-foreground">
                        In Slack, choose <span className="font-medium">“From an app manifest”</span>, pick the
                        workspace, then paste the JSON below (use the JSON tab).
                    </p>
                    <pre className="max-h-80 overflow-auto rounded-md border border-border bg-muted/20 p-2.5 text-[0.6875rem] leading-relaxed">
                        <code className="font-mono">{manifestJson}</code>
                    </pre>
                    <dl className="space-y-1 text-[0.6875rem]">
                        <RequestUrlRow label="Event Subscriptions Request URL" url={data.events_url} />
                        {/* Interactivity is only wired by the manifest when the agent has an
                         *  approval-gated tool — don't surface a URL Slack won't be told to use. */}
                        {(data.manifest as { settings?: { interactivity?: unknown } }).settings?.interactivity ? (
                            <RequestUrlRow label="Interactivity Request URL" url={data.interactivity_url} />
                        ) : null}
                    </dl>
                    {data.notes.length > 0 ? (
                        <ul className="list-disc space-y-0.5 pl-4 text-[0.625rem] text-muted-foreground">
                            {data.notes.map((note) => (
                                <li key={note}>{note}</li>
                            ))}
                        </ul>
                    ) : null}
                </div>
            ) : (
                <p className="px-4 py-3 text-xs text-muted-foreground">No manifest available.</p>
            )}
        </section>
    )
}

function RequestUrlRow({ label, url }: { label: string; url: string | null }): React.ReactElement {
    return (
        <div className="flex items-baseline gap-2">
            <dt className="shrink-0 text-muted-foreground">{label}:</dt>
            {url ? (
                <dd className="flex min-w-0 items-center gap-1.5">
                    <code className="truncate font-mono">{url}</code>
                    <CopyButton text={url} label="Copy" iconOnly />
                </dd>
            ) : (
                <dd className="text-muted-foreground/70 italic">not available (no public ingress URL configured)</dd>
            )}
        </div>
    )
}

function CopyButton({
    text,
    label,
    iconOnly = false,
}: {
    text: string
    label: string
    iconOnly?: boolean
}): React.ReactElement {
    const [copied, setCopied] = useState(false)
    const copy = async (): Promise<void> => {
        try {
            await navigator.clipboard.writeText(text)
            setCopied(true)
            setTimeout(() => setCopied(false), 1500)
        } catch {
            // Clipboard can be blocked (insecure context / permissions) — no-op,
            // the manifest is still visible for manual selection.
        }
    }
    return (
        <button
            type="button"
            onClick={copy}
            aria-label={label}
            className="inline-flex h-7 items-center gap-1 rounded-md border border-border bg-card px-2 text-[0.6875rem] font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
        >
            {copied ? <CheckIcon className="h-3 w-3 text-success-foreground" /> : <CopyIcon className="h-3 w-3" />}
            {iconOnly ? null : copied ? 'Copied' : label}
        </button>
    )
}

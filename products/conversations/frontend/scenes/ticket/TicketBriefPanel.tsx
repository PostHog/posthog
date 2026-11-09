import { LemonCollapse, LemonTag, Link } from '@posthog/lemon-ui'

import type { TicketBriefApi, TicketBriefItemKindEnumApi } from '../../generated/api.schemas'

const ITEM_KIND_LABELS: Record<TicketBriefItemKindEnumApi, string> = {
    dashboard: 'Dashboard',
    experiment: 'Experiment',
    feature_flag: 'Feature flag',
    insight: 'Insight',
    project: 'Project',
    replay: 'Replay',
    survey: 'Survey',
    external: 'Link',
    other: 'Item',
}

const FALLBACK_ITEM_KIND_LABEL = 'Item'

interface TicketBriefPanelProps {
    brief: TicketBriefApi
}

// Support triage quotes identifiers and error text in backticks, so those spans render as code.
// Split rather than rendered as markdown: the text is the customer's, relayed by an agent, so
// nothing else in it may become markup.
function Inline({ text }: { text: string }): JSX.Element {
    const parts = text.split(/`([^`]+)`/)
    return (
        <>
            {parts.map((part, index) =>
                index % 2 === 1 ? (
                    <code key={index} className="rounded bg-accent-highlight-secondary px-1 text-[11px]">
                        {part}
                    </code>
                ) : (
                    part
                )
            )}
        </>
    )
}

function BriefText({ label, text }: { label: string; text: string | null | undefined }): JSX.Element | null {
    if (!text) {
        return null
    }
    return (
        <div className="min-w-0">
            <div className="text-muted-alt">{label}</div>
            <p className="m-0 mt-0.5 break-words">
                <Inline text={text} />
            </p>
        </div>
    )
}

function BriefSection({ label, items }: { label: string; items: string[] }): JSX.Element | null {
    if (items.length === 0) {
        return null
    }
    return (
        <div className="min-w-0">
            <div className="text-muted-alt">{label}</div>
            <ul className="m-0 mt-0.5 pl-4 list-disc space-y-0.5 break-words">
                {items.map((item, index) => (
                    <li key={`${item}-${index}`}>
                        <Inline text={item} />
                    </li>
                ))}
            </ul>
        </div>
    )
}

// The error is quoted exactly, so it keeps its own line breaks and never runs through Inline:
// a stack trace or a JSON body can hold a stray backtick that would swallow half the text.
function BriefError({ error }: { error: string | null | undefined }): JSX.Element | null {
    if (!error) {
        return null
    }
    return (
        <div className="min-w-0">
            <div className="text-muted-alt">Error</div>
            <pre className="m-0 mt-0.5 p-1 rounded bg-accent-highlight-secondary text-[11px] whitespace-pre-wrap break-words">
                {error}
            </pre>
        </div>
    )
}

function briefLinks(brief: TicketBriefApi): { key: string; label: string; url: string }[] {
    const links = [
        // An item with no url is dropped rather than rendered, because a Link with no target
        // looks like the rest of the list and leads nowhere.
        ...(brief.affected_items ?? [])
            .filter((item) => !!item.url)
            .map((item) => ({
                label: `${ITEM_KIND_LABELS[item.kind] ?? FALLBACK_ITEM_KIND_LABEL}: ${item.label || 'Untitled'}`,
                url: item.url,
            })),
        ...(brief.replay_url ? [{ label: 'Session replay', url: brief.replay_url }] : []),
        ...(brief.screenshot_urls ?? []).map((url, index) => ({ label: `Screenshot ${index + 1}`, url })),
    ]
    // A key is the url plus its position, because the agent can cite one url under two labels
    // and React drops the duplicate.
    return links.map((link, index) => ({ ...link, key: `${link.url}-${index}` }))
}

function BriefLinks({ brief }: { brief: TicketBriefApi }): JSX.Element | null {
    const links = briefLinks(brief)
    if (links.length === 0) {
        return null
    }
    return (
        <div className="min-w-0">
            <div className="text-muted-alt">Links</div>
            <ul className="m-0 mt-0.5 pl-0 list-none space-y-0.5">
                {links.map((link) => (
                    <li key={link.key} className="min-w-0">
                        {/* `block` so the ellipsis applies: truncate does nothing on the
                            inline anchor Link renders by default. */}
                        <Link to={link.url} target="_blank" className="block truncate">
                            {link.label}
                        </Link>
                    </li>
                ))}
            </ul>
        </div>
    )
}

// A brief is written by an agent, so a field the schema calls required can still be missing on
// one already stored. Render what is there and keep the sidebar up.
export function TicketBriefPanel({ brief }: TicketBriefPanelProps): JSX.Element | null {
    const questions = brief.questions ?? []
    const facts = brief.facts ?? []
    const tried = brief.tried ?? []
    const links = briefLinks(brief)
    const isEmpty =
        !brief.ask &&
        !brief.purpose &&
        !brief.error_message &&
        questions.length === 0 &&
        facts.length === 0 &&
        tried.length === 0 &&
        links.length === 0
    if (isEmpty) {
        return null
    }

    return (
        <LemonCollapse
            className="bg-surface-primary"
            defaultActiveKey="ticket_brief"
            panels={[
                {
                    key: 'ticket_brief',
                    header: (
                        <span className="flex items-center min-w-0">
                            Ticket brief
                            {brief.area ? (
                                <LemonTag size="small" className="ml-1">
                                    {brief.area}
                                </LemonTag>
                            ) : null}
                        </span>
                    ),
                    content: (
                        <div className="space-y-2 text-xs min-w-0">
                            <BriefText label="Wants" text={brief.ask} />
                            <BriefText label="So they can" text={brief.purpose} />
                            <BriefSection label="Asking" items={questions} />
                            <BriefSection label="Tried" items={tried} />
                            <BriefError error={brief.error_message} />
                            <BriefSection label="Facts" items={facts} />
                            <BriefLinks brief={brief} />
                        </div>
                    ),
                },
            ]}
        />
    )
}

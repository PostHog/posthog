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

function briefLinks(brief: TicketBriefApi): { key: string; label: string; url: string }[] {
    const links = [
        ...(brief.affected_items ?? []).map((item) => ({
            label: `${ITEM_KIND_LABELS[item.kind] ?? FALLBACK_ITEM_KIND_LABEL}: ${item.label}`,
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
                        <Link to={link.url} target="_blank" className="truncate">
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
    if (!brief.ask && questions.length === 0 && facts.length === 0 && tried.length === 0 && links.length === 0) {
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
                            {brief.ask ? (
                                <div className="min-w-0">
                                    <div className="text-muted-alt">Wants</div>
                                    <p className="m-0 mt-0.5 break-words">
                                        <Inline text={brief.ask} />
                                    </p>
                                </div>
                            ) : null}
                            <BriefSection label="Asking" items={questions} />
                            <BriefSection label="Facts" items={facts} />
                            <BriefSection label="Tried" items={tried} />
                            <BriefLinks brief={brief} />
                        </div>
                    ),
                },
            ]}
        />
    )
}

import { LemonTag, Link } from '@posthog/lemon-ui'

import { KnowledgeSource } from '../scenes/businessKnowledgeLogic'

function inAppPath(url: string): string {
    // Lemon Link treats https as external, so strip the origin. Keep /project/:id
    // because the ticket may live on a child environment, not this project.
    try {
        const parsed = new URL(url)
        return `${parsed.pathname}${parsed.search}`
    } catch {
        return url
    }
}

export function KnowledgeSourceNameCell({ source }: { source: KnowledgeSource }): JSX.Element {
    return (
        <div className="flex flex-col min-w-0 max-w-full">
            <span className="flex items-center gap-1 min-w-0">
                <strong className="truncate">{source.name}</strong>
                {source.is_generated ? (
                    <LemonTag
                        type="highlight"
                        title="PostHog added this from a resolved support ticket. You can edit or delete it."
                    >
                        Learned
                    </LemonTag>
                ) : null}
                {source.has_unsafe_documents ? (
                    <LemonTag
                        type="danger"
                        title="One or more documents were flagged unsafe by the content classifier and are excluded from agent search."
                    >
                        unsafe content
                    </LemonTag>
                ) : null}
            </span>
            {source.is_generated && source.learned_from_ticket_number != null ? (
                source.learned_from_ticket_url ? (
                    <Link
                        to={inAppPath(source.learned_from_ticket_url)}
                        className="text-xs text-muted truncate"
                        // pinned: autocapture / Playwright key. Do not rename.
                        data-attr="business-knowledge-learned-ticket"
                        onClick={(e) => e.stopPropagation()}
                        target="_blank"
                    >
                        Learned from ticket #{source.learned_from_ticket_number}
                    </Link>
                ) : (
                    <span className="text-xs text-muted truncate">
                        Learned from ticket #{source.learned_from_ticket_number}
                    </span>
                )
            ) : source.source_type === 'url' && source.source_url ? (
                <Link
                    to={source.source_url}
                    target="_blank"
                    className="text-xs text-muted truncate"
                    onClick={(e) => e.stopPropagation()}
                >
                    {source.source_url}
                </Link>
            ) : source.source_type === 'file' && source.original_filename ? (
                <span className="text-xs text-muted truncate">{source.original_filename}</span>
            ) : null}
        </div>
    )
}

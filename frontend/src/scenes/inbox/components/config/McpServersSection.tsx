import { IconChevronRight, IconServer } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

export function McpServersSection(): JSX.Element {
    return (
        <Link
            to={urls.settings('mcp-servers')}
            className="group flex items-center justify-between gap-3 rounded border bg-bg-light px-3 py-2.5 no-underline transition-colors hover:border-primary-3000 hover:bg-bg-3000"
        >
            <div className="flex items-start gap-3 min-w-0">
                <IconServer className="size-5 shrink-0 mt-0.5 text-secondary" />
                <div className="min-w-0">
                    <div className="font-medium text-sm text-default">Manage MCP servers</div>
                    <p className="text-xs text-secondary mt-0.5 mb-0 max-w-xl">
                        External tools agents can read from. PostHog data is always available; this is everything else —
                        connect or disconnect Notion, PagerDuty, Linear, Zendesk, GitHub, anything that speaks MCP.
                    </p>
                </div>
            </div>
            <IconChevronRight className="size-4 shrink-0 text-muted transition-colors group-hover:text-default" />
        </Link>
    )
}

import { IconServer } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

export function McpServersSection(): JSX.Element {
    return (
        <div className="flex items-center justify-between gap-4 rounded border bg-bg-light px-3 py-2.5">
            <div className="flex items-start gap-3 min-w-0">
                <IconServer className="size-5 shrink-0 mt-0.5 text-secondary" />
                <div className="min-w-0">
                    <div className="font-medium text-sm">Manage MCP servers</div>
                    <p className="text-xs text-secondary mt-0.5 mb-0 max-w-xl">
                        External tools agents can read from. PostHog data is always available; this is everything else —
                        connect or disconnect Notion, PagerDuty, Linear, Zendesk, GitHub, anything that speaks MCP.
                    </p>
                </div>
            </div>
            <LemonButton type="secondary" size="small" to={urls.settings('mcp-servers')} targetBlank>
                Manage
            </LemonButton>
        </div>
    )
}

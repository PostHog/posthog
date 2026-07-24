import { useMountedLogic, useValues } from 'kea'

import { IconChevronRight, IconServer } from '@posthog/icons'
import { LemonTag, LemonTagType, Link, Spinner } from '@posthog/lemon-ui'
import { ServerIcon } from '@posthog/products-mcp-store/frontend/scene/icons'

import { urls } from 'scenes/urls'

import type { MCPServiceAccountServerApi } from 'products/mcp_store/frontend/generated/api.schemas'

import { scoutMcpServersLogic } from '../../logics/scoutMcpServersLogic'

const CONNECTION_STATE: Record<
    MCPServiceAccountServerApi['connection_state'],
    { label: string; tagType: LemonTagType }
> = {
    ready: { label: 'Connection ready', tagType: 'success' },
    pending_oauth: { label: 'Pending OAuth', tagType: 'warning' },
    needs_reauth: { label: 'Reconnect', tagType: 'danger' },
    disabled: { label: 'Disabled', tagType: 'muted' },
    missing_credential: { label: 'Needs connection', tagType: 'warning' },
}

export function McpServersSection(): JSX.Element {
    useMountedLogic(scoutMcpServersLogic)
    const { scoutAccount, scoutServers, scoutServersLoading } = useValues(scoutMcpServersLogic)

    if (scoutServersLoading && scoutAccount === null) {
        return (
            <div className="flex items-center gap-2 rounded border border-dashed px-3 py-4 text-sm text-secondary">
                <Spinner /> Loading Scout MCP servers...
            </div>
        )
    }

    return (
        <div className="rounded border bg-bg-light overflow-hidden">
            {scoutServers.length === 0 ? (
                <div className="flex items-start gap-3 px-3 py-3">
                    <IconServer className="size-5 shrink-0 mt-0.5 text-secondary" />
                    <div className="min-w-0">
                        <div className="font-medium text-sm text-default">No MCP servers shared with Scout</div>
                        <p className="text-xs text-secondary mt-0.5 mb-0">
                            A project admin can share a connection with the Scout agent.
                        </p>
                    </div>
                </div>
            ) : (
                <div className="divide-y">
                    {scoutServers.map((server) => {
                        const state = CONNECTION_STATE[server.connection_state]
                        return (
                            <div key={server.id} className="flex items-center gap-3 px-3 py-2.5">
                                <ServerIcon iconDomain={server.icon_domain} size={28} />
                                <div className="min-w-0 flex-1">
                                    <div className="font-medium text-sm text-default truncate">{server.name}</div>
                                    {server.description && (
                                        <div className="text-xs text-secondary truncate">{server.description}</div>
                                    )}
                                </div>
                                <LemonTag type={state.tagType} size="small">
                                    {state.label}
                                </LemonTag>
                            </div>
                        )
                    })}
                </div>
            )}
            <Link
                to={urls.settings('mcp-servers')}
                className="group flex items-center justify-between gap-3 border-t px-3 py-2 text-xs no-underline transition-colors hover:bg-bg-3000"
            >
                <span className="text-secondary group-hover:text-default">View MCP server settings</span>
                <IconChevronRight className="size-4 shrink-0 text-muted transition-colors group-hover:text-default" />
            </Link>
            {scoutAccount !== null && !scoutAccount.product_enabled ? (
                <div className="border-t px-3 py-2 text-xs text-secondary">
                    {scoutAccount.product_disabled_reason || 'Scout is unavailable.'}
                </div>
            ) : scoutAccount?.status === 'paused' ? (
                <div className="border-t px-3 py-2 text-xs text-secondary">Scout MCP access is paused.</div>
            ) : null}
        </div>
    )
}

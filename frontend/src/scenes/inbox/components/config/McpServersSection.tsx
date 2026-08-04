import { useMountedLogic, useValues } from 'kea'

import { IconChevronRight, IconServer } from '@posthog/icons'
import { LemonTag, LemonTagType, Link, Spinner } from '@posthog/lemon-ui'
import { ServerIcon } from '@posthog/products-mcp-store/frontend/scene/icons'

import { urls } from 'scenes/urls'

import type { MCPServiceAccountServerApi } from 'products/mcp_store/frontend/generated/api.schemas'

import { scoutMcpServersLogic } from '../../logics/scoutMcpServersLogic'

// Only states that need someone to act carry a tag. A healthy connection says nothing, so a long
// list of working apps stays quiet and anything broken is the only thing with color on it.
const NEEDS_ATTENTION: Partial<
    Record<MCPServiceAccountServerApi['connection_state'], { label: string; tagType: LemonTagType }>
> = {
    pending_oauth: { label: 'Finish connecting', tagType: 'warning' },
    needs_reauth: { label: 'Reconnect', tagType: 'danger' },
    disabled: { label: 'Turned off', tagType: 'muted' },
    missing_credential: { label: 'Needs connection', tagType: 'warning' },
}

function ServerRow({ server }: { server: MCPServiceAccountServerApi }): JSX.Element {
    const attention = NEEDS_ATTENTION[server.connection_state]
    return (
        <div className="flex items-center gap-3 px-3 py-2.5">
            <ServerIcon iconDomain={server.icon_domain} serverUrl={server.url} size={28} />
            <div className="min-w-0 flex-1">
                <div className="font-medium text-sm text-default truncate">{server.name}</div>
                {server.description && <div className="text-xs text-secondary truncate">{server.description}</div>}
            </div>
            {attention && (
                <LemonTag type={attention.tagType} size="small">
                    {attention.label}
                </LemonTag>
            )}
        </div>
    )
}

export function McpServersSection(): JSX.Element {
    useMountedLogic(scoutMcpServersLogic)
    const { scoutAccount, scoutServers, scoutServersLoading } = useValues(scoutMcpServersLogic)

    if (scoutServersLoading && scoutAccount === null) {
        return (
            <div className="flex items-center gap-2 rounded border border-dashed px-3 py-4 text-sm text-secondary">
                <Spinner /> Loading the apps Scout can use...
            </div>
        )
    }

    const needingAttention = scoutServers.filter((server) => server.connection_state in NEEDS_ATTENTION).length

    return (
        <div className="rounded border bg-bg-light overflow-hidden">
            {scoutServers.length === 0 ? (
                <div className="flex items-start gap-3 px-3 py-3">
                    <IconServer className="size-5 shrink-0 mt-0.5 text-secondary" />
                    <div className="min-w-0">
                        <div className="font-medium text-sm text-default">Scout can't use any apps yet</div>
                        <p className="text-xs text-secondary mt-0.5 mb-0">
                            Connect an app in MCP server settings, then share it with Scout to let it read from your
                            other tools while investigating.
                        </p>
                    </div>
                </div>
            ) : (
                <>
                    <div className="flex items-center justify-between gap-2 border-b px-3 py-2">
                        <span className="text-xs font-medium text-secondary">
                            {scoutServers.length === 1 ? '1 app' : `${scoutServers.length} apps`} shared with Scout
                        </span>
                        {needingAttention > 0 && (
                            <LemonTag type="warning" size="small">
                                {needingAttention === 1 ? '1 needs attention' : `${needingAttention} need attention`}
                            </LemonTag>
                        )}
                    </div>
                    <div className="divide-y">
                        {scoutServers.map((server) => (
                            <ServerRow key={server.id} server={server} />
                        ))}
                    </div>
                </>
            )}
            <Link
                to={urls.settings('mcp-servers')}
                className="group flex items-center justify-between gap-3 border-t px-3 py-2 text-xs no-underline transition-colors hover:bg-bg-3000"
            >
                <span className="text-secondary group-hover:text-default">Manage apps and MCP servers</span>
                <IconChevronRight className="size-4 shrink-0 text-muted transition-colors group-hover:text-default" />
            </Link>
            {scoutAccount?.status === 'paused' ? (
                <div className="border-t px-3 py-2 text-xs text-secondary">Scout's access to these apps is paused.</div>
            ) : null}
        </div>
    )
}

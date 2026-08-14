import { useActions, useValues } from 'kea'

import { IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonCard, LemonSwitch, LemonTag, LemonTagType, Link, Spinner } from '@posthog/lemon-ui'
import { agentServerAccessKey } from '@posthog/products-mcp-store/frontend/gateway/mcpGatewayLogic'
import type { ConnectionStateEnumApi } from '@posthog/products-mcp-store/frontend/generated/api.schemas'
import { ServerIcon } from '@posthog/products-mcp-store/frontend/scene/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { fullName } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { SupportMcpServerRow, supportMcpServersLogic } from './supportMcpServersLogic'

const VISIBLE_SERVER_COUNT = 3

/** Grant credential states worth surfacing; 'ready' needs no tag. */
const GRANT_STATE_TAGS: Partial<Record<ConnectionStateEnumApi, { label: string; tagType: LemonTagType }>> = {
    pending_oauth: { label: 'Pending OAuth', tagType: 'warning' },
    needs_reauth: { label: 'Reconnect', tagType: 'danger' },
    disabled: { label: 'Disabled', tagType: 'muted' },
    missing_credential: { label: 'Needs connection', tagType: 'warning' },
}

export function SupportMcpServersSection(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    // The gateway flag gates both this UI and backend enforcement of agent grants;
    // without it a share would have no effect on support runs.
    if (!featureFlags[FEATURE_FLAGS.MCP_GATEWAY]) {
        return null
    }
    return <SupportMcpServersSectionContent />
}

function SupportMcpServersSectionContent(): JSX.Element {
    const { showAllServers, supportAccount, supportMcpLoading, supportServerRows } = useValues(supportMcpServersLogic)
    const { setShowAllServers } = useActions(supportMcpServersLogic)

    const hiddenCount = supportServerRows.length - VISIBLE_SERVER_COUNT
    const visibleRows = showAllServers ? supportServerRows : supportServerRows.slice(0, VISIBLE_SERVER_COUNT)

    return (
        <SceneSection
            title="MCP servers"
            titleSize="sm"
            className="my-8"
            description="Give the support agent access to MCP servers you've connected. A server you share here is used through your connection for every support agent reply in this project, including replies generated automatically."
        >
            <LemonCard hoverEffect={false} className="max-w-[800px] p-0 overflow-hidden">
                {supportMcpLoading && supportServerRows.length === 0 ? (
                    <div className="flex items-center gap-2 px-4 py-3 text-sm text-muted-alt">
                        <Spinner /> Loading MCP servers...
                    </div>
                ) : supportServerRows.length === 0 ? (
                    <div className="px-4 py-3">
                        <div className="font-medium text-sm">No MCP servers connected yet</div>
                        <p className="text-xs text-muted-alt mt-0.5 mb-0">
                            Connect a server on the <Link to={urls.mcpGateway()}>MCP servers page</Link>, then share it
                            with the support agent here.
                        </p>
                    </div>
                ) : (
                    <>
                        <div className="divide-y">
                            {visibleRows.map((row) => (
                                <ServerRow key={row.server.id} row={row} />
                            ))}
                        </div>
                        {hiddenCount > 0 && (
                            <LemonButton
                                fullWidth
                                center
                                size="xsmall"
                                className="border-t rounded-none"
                                onClick={() => setShowAllServers(!showAllServers)}
                            >
                                {showAllServers ? 'View less' : `View ${hiddenCount} more`}
                            </LemonButton>
                        )}
                    </>
                )}
                {supportServerRows.length > 0 && (
                    <div className="border-t">
                        <Link
                            to={urls.mcpGateway()}
                            className="group flex items-center justify-between gap-3 px-4 py-2 text-xs no-underline transition-colors hover:bg-bg-3000"
                        >
                            <span className="text-muted-alt group-hover:text-default">Connect more MCP servers</span>
                            <IconChevronRight className="size-4 shrink-0 text-muted transition-colors group-hover:text-default" />
                        </Link>
                    </div>
                )}
                {supportAccount?.status === 'paused' && (
                    <div className="border-t px-4 py-2 text-xs text-muted-alt">
                        MCP access for the support agent is paused, so shared servers aren't used. Resume it on the{' '}
                        <Link to={urls.mcpGateway()}>MCP servers page</Link>.
                    </div>
                )}
            </LemonCard>
        </SceneSection>
    )
}

function ServerRow({ row }: { row: SupportMcpServerRow }): JSX.Element {
    const { agentServerAccessLoadingKeys, canManageAgentAccess, supportAccount } = useValues(supportMcpServersLogic)
    const { setAgentServerAccess } = useActions(supportMcpServersLogic)

    const { server, share, sharedWithTeamByYou, yourGrantState } = row
    const needsConnection = !share.sharedByYou && server.your_connection === null
    const stateTag = yourGrantState && yourGrantState !== 'ready' ? GRANT_STATE_TAGS[yourGrantState] : undefined

    let secondary: string
    if (sharedWithTeamByYou) {
        secondary = 'Shared through your connection'
    } else if (share.sharedByYou) {
        secondary = 'Shared for your runs only. Turn on to cover every support reply.'
    } else if (share.teamSharedByOthers.length > 0) {
        const [first, ...rest] = share.teamSharedByOthers
        const name = fullName(first) || first.email
        secondary = `Shared to the team by ${name}${rest.length > 0 ? ` and ${rest.length} other${rest.length === 1 ? '' : 's'}` : ''}`
    } else {
        secondary = 'Not shared'
    }

    const disabledReason = !supportAccount
        ? 'The support agent is not available in this project yet'
        : !canManageAgentAccess
          ? 'A project admin has turned off agent access management for members'
          : needsConnection
            ? 'Connect this server before sharing it with the support agent'
            : undefined

    return (
        <div className="flex items-center gap-3 px-4 py-2.5">
            <ServerIcon iconDomain={server.icon_domain} serverUrl={server.url} size={28} />
            <div className="min-w-0 flex-1">
                <div className="font-medium text-sm truncate">{server.name}</div>
                <div className="text-xs text-muted-alt truncate">{secondary}</div>
            </div>
            {stateTag && (
                <LemonTag type={stateTag.tagType} size="small">
                    {stateTag.label}
                </LemonTag>
            )}
            <LemonSwitch
                checked={sharedWithTeamByYou}
                loading={
                    supportAccount
                        ? agentServerAccessLoadingKeys.has(agentServerAccessKey(supportAccount.id, server.id))
                        : false
                }
                disabledReason={disabledReason}
                aria-label={`${sharedWithTeamByYou ? 'Stop sharing' : 'Share'} your ${server.name} connection with the support agent`}
                onChange={(checked) => {
                    if (supportAccount) {
                        setAgentServerAccess(supportAccount.id, server.id, checked, 'team')
                    }
                }}
            />
        </div>
    )
}

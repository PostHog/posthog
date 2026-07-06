import { useActions, useMountedLogic, useValues } from 'kea'

import { IconBolt, IconCheckCircle, IconChevronRight, IconCompass, IconGithub, IconServer } from '@posthog/icons'
import { LemonModal, LemonSkeleton, LemonTag, Link } from '@posthog/lemon-ui'
import { mcpStoreLogic } from '@posthog/products-mcp-store/frontend/mcpStoreLogic'
import { ServerIcon } from '@posthog/products-mcp-store/frontend/scene/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { slackChannelDisplayName } from 'lib/integrations/slackChannel'
import { IconSlack } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { cn } from 'lib/utils/css-classes'
import { urls } from 'scenes/urls'

import { scoutFleetLogic } from '../../logics/scoutFleetLogic'
import { userAutonomyLogic } from '../../logics/userAutonomyLogic'
import { signalSourcesLogic } from '../../signalSourcesLogic'
import { ScoutsFleetSection } from '../config/scouts/ScoutsFleetSection'
import { SignalSourcesPanel } from '../config/SignalSourcesPanel'
import { SlackNotificationsSection } from '../config/SlackNotificationsSection'
import { AgentSetupModalKey, agentSetupModalLogic } from './agentSetupModalLogic'
import { InboxUsageWidget } from './InboxUsageWidget'

type WidgetTone = 'todo' | 'done' | 'neutral'
/** Visual weight reflecting how important / frequently edited a part of the setup is. */
type WidgetSize = 'lg' | 'md' | 'sm'

interface SetupWidgetCardProps {
    icon: JSX.Element
    title: string
    /** Short status line; falls back to a skeleton while `loading`. */
    status: React.ReactNode
    tone: WidgetTone
    size: WidgetSize
    loading?: boolean
    /** One-line context, shown on `lg` cards only. */
    description?: string
    /** Modal-backed widgets pass `onClick`; link-out widgets (Code access, MCP) pass `to`. */
    onClick?: () => void
    to?: string
    /** Extra content under the status (e.g. MCP brand icons). */
    children?: React.ReactNode
}

function TrailingAffordance({
    tone,
    to,
    loading,
}: {
    tone: WidgetTone
    to?: string
    loading?: boolean
}): JSX.Element | null {
    if (loading) {
        return <LemonSkeleton className="h-4 w-12 rounded" />
    }
    if (tone === 'todo') {
        return (
            <LemonTag type="warning" size="small">
                Set up
            </LemonTag>
        )
    }
    if (tone === 'done') {
        return <IconCheckCircle className="size-4 shrink-0 text-success" />
    }
    if (to) {
        return <IconChevronRight className="size-4 shrink-0 text-muted transition-colors group-hover:text-default" />
    }
    return null
}

const ICON_BOX_CLASS: Record<WidgetSize, string> = {
    sm: 'size-5 [&_svg]:size-3',
    md: 'size-6 [&_svg]:size-3.5',
    lg: 'size-7 [&_svg]:size-4',
}
const TITLE_CLASS: Record<WidgetSize, string> = {
    sm: 'text-[13px] font-medium',
    md: 'text-[13px] font-medium',
    lg: 'text-[13px] font-semibold',
}
const CARD_PADDING_CLASS: Record<WidgetSize, string> = {
    sm: 'px-2.5 py-1.5',
    md: 'px-2.5 py-2',
    lg: 'px-2.5 py-2 gap-0.5',
}

function SetupWidgetCard(props: SetupWidgetCardProps): JSX.Element {
    const { icon, title, status, tone, size, loading, description, onClick, to, children } = props

    const cardClassName = cn(
        'group flex rounded border border-primary bg-surface-primary text-left no-underline cursor-pointer transition-colors hover:border-secondary',
        size === 'sm' ? 'items-center justify-between gap-2' : 'flex-col',
        CARD_PADDING_CLASS[size]
    )

    // Compact single-row layout for the lowest-importance widgets.
    const content =
        size === 'sm' ? (
            <>
                <div className="flex items-center gap-2 min-w-0">
                    <span
                        className={cn(
                            'flex shrink-0 items-center justify-center rounded bg-surface-secondary text-default',
                            ICON_BOX_CLASS[size]
                        )}
                    >
                        {icon}
                    </span>
                    <span className={cn('text-default truncate', TITLE_CLASS[size])}>{title}</span>
                </div>
                <div className="flex items-center gap-1.5 shrink-0">
                    {loading ? (
                        <LemonSkeleton className="h-3 w-16" />
                    ) : (
                        <span className="text-xs text-secondary">{status}</span>
                    )}
                    <TrailingAffordance tone={tone} to={to} loading={loading} />
                </div>
            </>
        ) : (
            <div className="flex items-start gap-2 min-w-0">
                <span
                    className={cn(
                        'flex shrink-0 items-center justify-center rounded bg-surface-secondary text-default',
                        ICON_BOX_CLASS[size]
                    )}
                >
                    {icon}
                </span>
                <div className="flex flex-col gap-0.5 min-w-0 flex-1">
                    <div className="flex items-center justify-between gap-1.5">
                        <span className={cn('text-default truncate', TITLE_CLASS[size])}>{title}</span>
                        <TrailingAffordance tone={tone} to={to} loading={loading} />
                    </div>
                    {loading ? (
                        <LemonSkeleton className="h-3 w-20" />
                    ) : (
                        <span className="text-xs text-secondary truncate">{status}</span>
                    )}
                    {size === 'lg' && description && (
                        <p className="text-xs text-tertiary leading-snug mb-0">{description}</p>
                    )}
                    {children}
                </div>
            </div>
        )

    if (to) {
        return (
            <Link to={to} className={cardClassName}>
                {content}
            </Link>
        )
    }
    return (
        <button type="button" onClick={onClick} className={cardClassName}>
            {content}
        </button>
    )
}

function SignalSourcesWidget(): JSX.Element {
    const { sourceConfigs, enabledSourcesCount } = useValues(signalSourcesLogic)
    const { openSetupModal } = useActions(agentSetupModalLogic)
    const hasAny = enabledSourcesCount > 0
    return (
        <SetupWidgetCard
            icon={<IconBolt />}
            title="Signal sources"
            size="lg"
            tone={hasAny ? 'done' : 'todo'}
            loading={sourceConfigs === null}
            status={hasAny ? `${enabledSourcesCount} watching` : 'None active yet'}
            description="Each source watches a product and spins up work when something matters."
            onClick={() => openSetupModal('signal-sources')}
        />
    )
}

function ScoutTroopWidget(): JSX.Element {
    useMountedLogic(scoutFleetLogic)
    const { scoutConfigs, enabledCount } = useValues(scoutFleetLogic)
    const { openSetupModal } = useActions(agentSetupModalLogic)
    const hasAny = enabledCount > 0
    return (
        <SetupWidgetCard
            icon={<IconCompass />}
            title="Scout troop"
            size="lg"
            tone={hasAny ? 'done' : 'todo'}
            loading={scoutConfigs === null}
            status={hasAny ? `${enabledCount} on patrol` : 'No scouts running'}
            description="Scheduled agents that sweep this project on a cadence and report findings."
            onClick={() => openSetupModal('scout-troop')}
        />
    )
}

function CodeAccessWidget(): JSX.Element {
    const { getIntegrationsByKind, integrationsLoading } = useValues(integrationsLogic)
    const hasGithub = getIntegrationsByKind(['github']).length > 0
    return (
        <SetupWidgetCard
            icon={<IconGithub />}
            title="Code access"
            size="md"
            tone={hasGithub ? 'done' : 'todo'}
            loading={integrationsLoading && !hasGithub}
            status={hasGithub ? 'GitHub connected' : 'Foundational – connect to start'}
            to={urls.settings('environment-integrations', 'integration-github')}
        />
    )
}

function McpServersWidget(): JSX.Element {
    useMountedLogic(mcpStoreLogic)
    const { installations, installationsLoading } = useValues(mcpStoreLogic)
    const count = installations.length
    return (
        <SetupWidgetCard
            icon={<IconServer />}
            title="MCP servers"
            size="md"
            tone={count > 0 ? 'done' : 'neutral'}
            loading={installationsLoading && count === 0}
            status={count > 0 ? `${count} connected` : 'Connect external tools'}
            to={urls.settings('mcp-servers')}
        >
            {count > 0 && (
                <div className="flex items-center gap-1 pt-1">
                    {installations.slice(0, 6).map((installation) => (
                        <ServerIcon key={installation.id} iconKey={installation.icon_key} size={16} />
                    ))}
                    {count > 6 && <span className="text-[11px] text-muted">+{count - 6}</span>}
                </div>
            )}
        </SetupWidgetCard>
    )
}

function NotificationsWidget(): JSX.Element {
    useMountedLogic(userAutonomyLogic)
    const { slackIntegrations, integrationsLoading } = useValues(integrationsLogic)
    const { autonomyConfig } = useValues(userAutonomyLogic)
    const { openSetupModal } = useActions(agentSetupModalLogic)

    const channel = autonomyConfig?.slack_notification_channel ?? null
    const notifying = (slackIntegrations?.length ?? 0) > 0 && !!channel
    return (
        <SetupWidgetCard
            icon={<IconSlack className="grayscale" />}
            title="Notifications"
            size="md"
            tone={notifying ? 'done' : 'todo'}
            loading={integrationsLoading && slackIntegrations === undefined}
            status={notifying && channel ? `Slack ${slackChannelDisplayName(channel)}` : 'Not connected'}
            onClick={() => openSetupModal('slack')}
        />
    )
}

/** Section heading styled like a LemonTabs label (same 14px scale, tertiary color) so the
 * rail reads as a sibling of the tab bar rather than a louder header. */
function SetupSection({ title, children }: { title: string; children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex flex-col">
            <h4 className="text-sm font-medium text-tertiary mt-0 mb-3.5">{title}</h4>
            <div className="flex flex-col gap-1.5">{children}</div>
        </div>
    )
}

const SETUP_MODALS: Record<
    AgentSetupModalKey,
    { title: string; description: string; width: number; body: JSX.Element }
> = {
    'signal-sources': {
        title: 'Signal sources',
        description: 'Each source watches for signals and spins up work when something matters.',
        width: 760,
        body: <SignalSourcesPanel />,
    },
    'scout-troop': {
        title: 'Scout troop',
        description: 'Scheduled agents that sweep this project on a cadence and emit findings to your inbox.',
        width: 760,
        body: <ScoutsFleetSection />,
    },
    slack: {
        title: 'Notifications',
        description: 'Get pinged in Slack when you’re a suggested reviewer on a new inbox item.',
        width: 560,
        body: <SlackNotificationsSection />,
    },
}

function SetupModal(): JSX.Element {
    const { openModal } = useValues(agentSetupModalLogic)
    const { closeSetupModal } = useActions(agentSetupModalLogic)
    const config = openModal ? SETUP_MODALS[openModal] : null
    return (
        <LemonModal
            isOpen={config !== null}
            onClose={closeSetupModal}
            title={config?.title ?? ''}
            description={config?.description}
            width={config?.width}
        >
            {config?.body}
        </LemonModal>
    )
}

/**
 * The agent-setup widgets, grouped into Agents / Connections. Each widget shows
 * status and nudges the user to finish that part of the setup. Signal sources and Scout troop
 * (most edited) are largest; connections medium. Code access and MCP link
 * out to settings; the rest open a management modal.
 *
 * Rendered two ways: `rail` (a column to the right of the tabs on wide viewports) and
 * `stacked` (the Configuration tab body on narrow viewports).
 */
export function AgentSetupColumn({ layout }: { layout: 'rail' | 'stacked' }): JSX.Element {
    useMountedLogic(integrationsLogic)
    useMountedLogic(signalSourcesLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    return (
        <div
            className={cn(
                'flex flex-col gap-5',
                layout === 'stacked' ? 'mx-auto w-full max-w-2xl px-6 py-6' : 'px-4 py-3'
            )}
        >
            <SetupSection title="Agents">
                <SignalSourcesWidget />
                <ScoutTroopWidget />
            </SetupSection>
            <SetupSection title="Connections">
                <CodeAccessWidget />
                <NotificationsWidget />
                {featureFlags[FEATURE_FLAGS.MCP_SERVERS] && <McpServersWidget />}
            </SetupSection>
            <SetupSection title="Usage">
                <InboxUsageWidget />
            </SetupSection>
            <SetupModal />
        </div>
    )
}

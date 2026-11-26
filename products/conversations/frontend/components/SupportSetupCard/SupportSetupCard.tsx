import { useActions, useValues } from 'kea'

import { IconChevronRight, IconCode } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import type { ProductEmptyStateMode } from 'lib/components/ProductEmptyState/types'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { FEATURE_FLAGS, TeamMembershipLevel } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { isAuthenticatedTeam, teamLogic } from 'scenes/teamLogic'

import type { TeamType } from '~/types'

import { channelIcon } from '../Channels/ChannelsTag'
import { SupportSetupAIAgent } from '../SupportSetupAIAgent/SupportSetupAIAgent'
import { SupportSetupImports } from '../SupportSetupImports/SupportSetupImports'
import { SupportSetupTestTicket } from '../SupportSetupTestTicket/SupportSetupTestTicket'
import { type SupportSetupChannel, supportSetupCardLogic } from './supportSetupCardLogic'

const COPY: Record<ProductEmptyStateMode, { title: string; lead: string }> = {
    'needs-setup': {
        title: 'Choose how customers reach you',
        lead: 'Picking a channel turns Support on. The widget needs no setup, and other channels open their settings.',
    },
    'waiting-for-data': {
        title: 'Connect a channel',
        lead: 'Tickets arrive from every channel you connect. You can use more than one.',
    },
}

const WIDGET_ON_COPY = {
    title: 'The widget is on',
    lead: 'It shows on pages that load the PostHog JavaScript SDK. You can connect more channels below.',
}

interface SetupChannel {
    key: SupportSetupChannel
    icon: JSX.Element
    title: string
    description: string
    connected?: boolean
}

function setupChannels(
    settings: TeamType['conversations_settings'] | undefined,
    widgetOn: boolean,
    teamsAvailable: boolean
): SetupChannel[] {
    return [
        {
            key: 'widget',
            icon: channelIcon.widget,
            title: 'Widget',
            description: widgetOn
                ? 'Change its color, position, and greeting.'
                : 'Add a chat bubble to your website or app. One click turns it on.',
            connected: !!settings?.widget_enabled,
        },
        {
            key: 'email',
            icon: channelIcon.email,
            title: 'Email',
            description: 'Receive and answer emails sent to your support address.',
            connected: !!settings?.email_enabled,
        },
        {
            key: 'slack',
            icon: channelIcon.slack,
            title: 'Slack',
            description: 'Turn Slack messages into tickets.',
            connected: !!settings?.slack_enabled,
        },
        ...(teamsAvailable
            ? [
                  {
                      key: 'teams' as const,
                      icon: channelIcon.teams,
                      title: 'Microsoft Teams',
                      description: 'Turn Teams messages into tickets.',
                      connected: !!settings?.teams_enabled,
                  },
              ]
            : []),
        {
            key: 'api',
            icon: <IconCode />,
            title: 'Direct API',
            description: 'Send tickets from your own contact form or custom UI.',
        },
    ]
}

export function SupportSetupCard({ mode, preview }: { mode: ProductEmptyStateMode; preview: boolean }): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { pendingChannel, pendingReason } = useValues(supportSetupCardLogic)
    const { pickChannel } = useActions(supportSetupCardLogic)

    const supportEnabled = !!currentTeam?.conversations_enabled
    const adminRestriction = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    // The server only lets project admins turn Support on. A preview never turns it on.
    const enableRestriction = !supportEnabled && !preview ? adminRestriction : null
    const settings = currentTeam?.conversations_settings
    const widgetOn = supportEnabled && !!settings?.widget_enabled
    const copy = widgetOn ? WIDGET_ON_COPY : COPY[mode]
    const aiAgentAvailable = !!featureFlags[FEATURE_FLAGS.PRODUCT_SUPPORT_AI_SUGGESTION_ORGS]

    const channels = setupChannels(settings, widgetOn, !!featureFlags[FEATURE_FLAGS.PRODUCT_SUPPORT_TEAMS_ENABLED])

    return (
        <div className="mt-2 flex flex-col overflow-hidden rounded border border-primary bg-surface-primary">
            <div className="flex flex-col gap-1 px-4 pb-3 pt-3.5">
                <span className="text-base font-semibold">{copy.title}</span>
                <span className="text-sm text-secondary">
                    {enableRestriction && isAuthenticatedTeam(currentTeam)
                        ? `${enableRestriction} Ask a project admin to turn Support on.`
                        : copy.lead}
                </span>
            </div>
            <div className="flex flex-col gap-px border-t border-primary p-1">
                {channels.map((channel) => (
                    <LemonButton
                        key={channel.key}
                        fullWidth
                        icon={channel.icon}
                        sideIcon={<IconChevronRight className="size-3" />}
                        loading={pendingChannel === channel.key}
                        disabledReason={
                            enableRestriction ??
                            (pendingChannel !== channel.key ? (pendingReason ?? undefined) : undefined)
                        }
                        onClick={() => pickChannel(channel.key, mode, preview)}
                        data-attr={`support-setup-channel-${channel.key}`}
                    >
                        <span className="flex min-w-0 flex-col py-0.5 text-left">
                            <span className="flex items-center gap-1.5 font-semibold">
                                {channel.title}
                                {supportEnabled && channel.connected ? (
                                    <LemonTag type="success" size="small">
                                        On
                                    </LemonTag>
                                ) : null}
                            </span>
                            <span className="whitespace-normal text-xs font-normal text-secondary">
                                {channel.description}
                            </span>
                        </span>
                    </LemonButton>
                ))}
            </div>
            {supportEnabled ? <SupportSetupTestTicket preview={preview} /> : null}
            <SupportSetupImports mode={mode} preview={preview} restrictionReason={enableRestriction} />
            {aiAgentAvailable ? <SupportSetupAIAgent supportEnabled={supportEnabled} /> : null}
        </div>
    )
}

import { BindLogic, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import * as wizardPng from '@posthog/brand/hoggies/png/wizard-1'

import { pngHoggie } from 'lib/brand/hoggies'
import { CommandBlock } from 'lib/components/CommandBlock/CommandBlock'
import { agentConnectionLogic } from 'lib/components/MCPHint/agentConnectionLogic'
import { MCP_INSTALL_COMMAND } from 'lib/components/MCPHint/constants'

import { AdvertisementCard, NAV_PANEL_CARD_TYPE, ProductPushDisplay } from './navPanelAdShared'
import { navPanelAdvertisementLogic } from './NavPanelAdvertisementLogic'

const logicProps = { dismissKey: 'mcp-connect' }

const MCP_HERO: ProductPushDisplay = {
    Hoggie: pngHoggie(wizardPng),
    accentColor: 'var(--color-accent)',
    tagline: '',
}

/**
 * Asks users whose agent has not connected to connect the PostHog MCP server. Renders `fallback`
 * when it has nothing to ask, so the ad slot falls through to the next card.
 */
export function NavPanelMcpAd({ fallback }: { fallback: JSX.Element | null }): JSX.Element | null {
    const { hidden } = useValues(navPanelAdvertisementLogic(logicProps))
    const { hasConnectedAgent, connectedAppsLoading } = useValues(agentConnectionLogic)
    // `null` means the lookup has not succeeded yet, which never counts as eligible.
    const shouldShow = !hidden && hasConnectedAgent === false

    useEffect(() => {
        if (shouldShow) {
            posthog.capture('nav panel mcp card shown', { card_type: NAV_PANEL_CARD_TYPE.MCP_CONNECT })
        }
    }, [shouldShow])

    // Hold the slot while the first load runs, so a lower card does not flash in and get replaced.
    if (connectedAppsLoading && hasConnectedAgent === null && !hidden) {
        return null
    }
    if (!shouldShow) {
        return fallback
    }

    return (
        <BindLogic logic={navPanelAdvertisementLogic} props={logicProps}>
            <AdvertisementCard
                title="Connect your AI agent"
                hero={MCP_HERO}
                text={
                    <span className="flex flex-col items-start gap-2">
                        <span>
                            Let Claude Code, Cursor, or Codex work with your PostHog data. Run this in your terminal:
                        </span>
                        <CommandBlock
                            command={MCP_INSTALL_COMMAND}
                            displayLines={['npx @posthog/wizard', 'mcp add']}
                            copyLabel="MCP install command"
                            ariaLabel="Copy MCP install command"
                            size="sm"
                            decoration="rainbow"
                            className="bg-surface-secondary border border-primary !m-0 max-w-full hover:border-accent"
                            onCopy={() =>
                                posthog.capture('nav panel mcp card command copied', {
                                    card_type: NAV_PANEL_CARD_TYPE.MCP_CONNECT,
                                })
                            }
                        />
                    </span>
                }
                onClose={() => {
                    posthog.capture('nav panel mcp card dismissed', { card_type: NAV_PANEL_CARD_TYPE.MCP_CONNECT })
                }}
            />
        </BindLogic>
    )
}

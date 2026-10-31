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

export const MCP_AD_LOGIC_PROPS = { dismissKey: 'mcp-connect' }

const MCP_HERO: ProductPushDisplay = {
    Hoggie: pngHoggie(wizardPng),
    accentColor: 'var(--color-accent)',
    tagline: '',
}

export function NavPanelMcpCard(): JSX.Element | null {
    const { hasConnectedAgent } = useValues(agentConnectionLogic)
    // `null` means no lookup has succeeded, which never counts as eligible.
    const shouldShow = hasConnectedAgent === false

    useEffect(() => {
        if (shouldShow) {
            posthog.capture('nav panel mcp card shown', { card_type: NAV_PANEL_CARD_TYPE.MCP_CONNECT })
        }
    }, [shouldShow])

    if (!shouldShow) {
        return null
    }

    return (
        <BindLogic logic={navPanelAdvertisementLogic} props={MCP_AD_LOGIC_PROPS}>
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
                            className="bg-surface-secondary border border-primary !m-0 max-w-full text-[11px] hover:border-accent"
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

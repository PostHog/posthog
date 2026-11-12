import { useValues } from 'kea'
import { useEffect } from 'react'

import { IconMCP } from '@posthog/icons'
import { Item, ItemActions, ItemContent, ItemDescription, ItemMedia, ItemTitle } from '@posthog/quill'

import { CommandBlock } from 'lib/components/CommandBlock/CommandBlock'
import { agentConnectionLogic } from 'lib/components/MCPHint/agentConnectionLogic'
import { MCP_INSTALL_COMMAND } from 'lib/components/MCPHint/constants'
import { captureMcpCardEvent } from 'lib/components/NavPanelAdvertisement/navPanelAdEvents'
import { NAV_PANEL_PLACEMENT } from 'lib/components/NavPanelAdvertisement/navPanelAdShared'
import { MCP_AD_LOGIC_PROPS } from 'lib/components/NavPanelAdvertisement/NavPanelMcpCard'

import { TodayPromoDismissButton } from './TodayPromoDismissButton'

export function TodayMcpCallout(): JSX.Element | null {
    const { hasConnectedAgent } = useValues(agentConnectionLogic)
    // `null` means no lookup has succeeded, which never counts as eligible.
    const shouldShow = hasConnectedAgent === false

    useEffect(() => {
        if (shouldShow) {
            captureMcpCardEvent('shown', NAV_PANEL_PLACEMENT.TODAY_HOME)
        }
    }, [shouldShow])

    if (!shouldShow) {
        return null
    }

    return (
        <Item variant="outline" className="mb-8" data-attr="today-mcp-banner">
            <ItemMedia variant="icon">
                <IconMCP />
            </ItemMedia>
            <ItemContent className="min-w-0">
                <ItemTitle>Connect your AI agent</ItemTitle>
                <ItemDescription className="line-clamp-none">
                    Let Claude Code, Cursor, or Codex work with your PostHog data. Run this in your terminal:
                </ItemDescription>
                <CommandBlock
                    command={MCP_INSTALL_COMMAND}
                    copyLabel="MCP install command"
                    ariaLabel="Copy MCP install command"
                    size="sm"
                    decoration="rainbow"
                    className="mt-1 max-w-full border border-border bg-muted"
                    onCopy={() => captureMcpCardEvent('commandCopied', NAV_PANEL_PLACEMENT.TODAY_HOME)}
                />
            </ItemContent>
            <ItemActions>
                <TodayPromoDismissButton
                    dismissKey={MCP_AD_LOGIC_PROPS.dismissKey}
                    onDismiss={() => captureMcpCardEvent('dismissed', NAV_PANEL_PLACEMENT.TODAY_HOME)}
                    dataAttr="today-mcp-banner-dismiss"
                />
            </ItemActions>
        </Item>
    )
}

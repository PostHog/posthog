import { useActions } from 'kea'

import { IconCopy } from '@posthog/icons'

import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'

import { CatalogSetupSource, catalogSetupLogic } from '../catalogSetupLogic'

export function CopyAgentSetupPromptButton({
    source,
    type = 'secondary',
}: {
    source: CatalogSetupSource
    type?: LemonButtonProps['type']
}): JSX.Element {
    const { copyAgentSetupPrompt } = useActions(catalogSetupLogic)

    return (
        <LemonButton
            type={type}
            icon={<IconCopy />}
            onClick={() => copyAgentSetupPrompt(source)}
            tooltip="Paste this prompt into Claude Code, Cursor, or any agent connected to the PostHog MCP server."
            // pinned: data-attr values feed autocapture dashboards
            data-attr={`data-catalog-copy-setup-prompt-${source}`}
        >
            Copy prompt for your agent
        </LemonButton>
    )
}

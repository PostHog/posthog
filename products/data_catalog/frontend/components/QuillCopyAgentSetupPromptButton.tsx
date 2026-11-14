import { useActions } from 'kea'

import { IconCopy } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { CatalogSetupSource, catalogSetupLogic } from '../catalogSetupLogic'

export function QuillCopyAgentSetupPromptButton({
    source,
    size,
}: {
    source: CatalogSetupSource
    size?: 'default' | 'sm'
}): JSX.Element {
    const { copyAgentSetupPrompt } = useActions(catalogSetupLogic)

    return (
        <Button
            variant="outline"
            size={size}
            tooltip="Paste this prompt into Claude Code, Cursor, or any agent connected to the PostHog MCP server."
            onClick={() => copyAgentSetupPrompt(source)}
            // pinned: data-attr values feed autocapture dashboards
            data-attr={`data-catalog-copy-setup-prompt-${source}`}
        >
            <IconCopy />
            Copy prompt for your agent
        </Button>
    )
}

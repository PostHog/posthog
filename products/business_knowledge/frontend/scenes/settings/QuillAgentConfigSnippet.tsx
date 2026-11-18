import { IconCopy } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { CodeLine, Language } from 'lib/components/CodeSnippet'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { agentMcpConfig, onAgentConfigCopied } from './AgentConfigSnippet'

export function QuillAgentConfigSnippet({ apiKey }: { apiKey?: string }): JSX.Element {
    const config = agentMcpConfig(apiKey)

    const copyConfig = (): void => {
        // Only report a copy the user actually got, as CodeSnippet does.
        void copyToClipboard(config, 'agent configuration').then((copied) => {
            if (copied) {
                onAgentConfigCopied()
            }
        })
    }

    // ph-no-capture keeps a newly created key out of session recordings.
    return (
        <div className="ph-no-capture relative rounded-md border border-border bg-muted py-2.5 ps-3 pe-10 font-mono text-xs">
            <CodeLine text={config} language={Language.JSON} wrapLines />
            <Button
                size="icon-xs"
                className="absolute end-1.5 top-1.5"
                aria-label="Copy to clipboard"
                tooltip="Copy to clipboard"
                onClick={copyConfig}
                data-attr="copy-code-button"
            >
                <IconCopy />
            </Button>
        </div>
    )
}

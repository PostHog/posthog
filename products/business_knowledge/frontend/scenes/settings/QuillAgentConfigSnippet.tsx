import { IconCopy } from '@posthog/icons'
import { Button, Card } from '@posthog/quill'

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
        <Card flush className="ph-no-capture flex-row items-start gap-0 py-0">
            <div className="min-w-0 flex-1 overflow-x-auto py-2.5 ps-3 font-mono text-xs">
                <CodeLine text={config} language={Language.JSON} wrapLines />
            </div>
            <div className="flex shrink-0 items-center p-1.5">
                <Button
                    size="icon"
                    aria-label="Copy to clipboard"
                    tooltip="Copy to clipboard"
                    onClick={copyConfig}
                    data-attr="copy-code-button"
                >
                    <IconCopy />
                </Button>
            </div>
        </Card>
    )
}

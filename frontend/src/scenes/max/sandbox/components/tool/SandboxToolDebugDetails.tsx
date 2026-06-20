import { CodeSnippet, Language } from 'lib/components/CodeSnippet/CodeSnippet'

import { ActivityToggleSection, renderContentBlocks } from '../../../components/Activity'
import type { SandboxToolCallMessage } from '../../../maxTypes'

/**
 * Staff/dev-only raw inspector for a tool call — the Input / Output / Raw output JSON toggles that
 * used to be every tool card's body. Gated upstream (`showRawDetails`); a normal user never sees it.
 * Appended inside a tool card's expanded box, below the elegant per-tool body.
 */
export function SandboxToolDebugDetails({ message }: { message: SandboxToolCallMessage }): JSX.Element {
    const contentText = message.content.length > 0 ? renderContentBlocks(message.content) : ''
    const outputText =
        message.rawOutput !== undefined && message.rawOutput !== null ? JSON.stringify(message.rawOutput, null, 2) : ''

    return (
        <div className="flex flex-col gap-1 border-t border-border-secondary pt-2 mt-2">
            <ActivityToggleSection title="Input">
                <CodeSnippet language={Language.JSON} compact>
                    {JSON.stringify(message.innerInput ?? message.rawInput, null, 2)}
                </CodeSnippet>
            </ActivityToggleSection>
            {contentText && (
                <ActivityToggleSection title="Output">
                    <CodeSnippet language={Language.Text} compact>
                        {contentText}
                    </CodeSnippet>
                </ActivityToggleSection>
            )}
            {outputText && (
                <ActivityToggleSection title="Raw output">
                    <CodeSnippet language={Language.JSON} compact>
                        {outputText}
                    </CodeSnippet>
                </ActivityToggleSection>
            )}
        </div>
    )
}

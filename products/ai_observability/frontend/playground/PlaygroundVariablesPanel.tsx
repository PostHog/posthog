import { useActions, useValues } from 'kea'

import { IconChevronRight, IconWarning } from '@posthog/icons'
import { LemonButton, LemonTag, LemonTextArea, Tooltip } from '@posthog/lemon-ui'

import { AnimatedCollapsible } from 'lib/components/AnimatedCollapsible'

import { llmPlaygroundPromptsLogic } from './llmPlaygroundPromptsLogic'
import { llmPlaygroundVariablesLogic } from './llmPlaygroundVariablesLogic'
import { getVariableValue } from './playgroundTemplating'

export function PlaygroundVariablesPanel(): JSX.Element {
    const { detectedVariables, unfilledVariables, variableValues } = useValues(llmPlaygroundVariablesLogic)
    const { setVariableValue } = useActions(llmPlaygroundVariablesLogic)
    const { collapsedSections } = useValues(llmPlaygroundPromptsLogic)
    const { toggleCollapsed } = useActions(llmPlaygroundPromptsLogic)

    const collapsed = !!collapsedSections['variables']

    return (
        <div className="border rounded p-4 py-2 shrink-0">
            <div className={`flex items-center gap-2 ${collapsed ? '' : 'mb-2'}`}>
                <LemonButton
                    size="small"
                    noPadding
                    icon={
                        <IconChevronRight className={`transition-transform ${collapsed ? 'rotate-0' : 'rotate-90'}`} />
                    }
                    onClick={() => toggleCollapsed('variables')}
                    aria-expanded={!collapsed}
                    data-attr="llma-playground-toggle-variables"
                >
                    Variables{detectedVariables.length > 0 ? ` (${detectedVariables.length})` : ''}
                </LemonButton>
                {unfilledVariables.length > 0 && (
                    <LemonTag type="warning" size="small">
                        {unfilledVariables.length} unfilled
                    </LemonTag>
                )}
            </div>

            <AnimatedCollapsible collapsed={collapsed}>
                {detectedVariables.length === 0 ? (
                    <p className="text-xs text-muted mb-1">
                        Add a placeholder like <code>{'{{topic}}'}</code> to the system prompt or a message, then fill
                        in a test value here. Values are applied when you run. Saved prompts keep the placeholders.
                    </p>
                ) : (
                    <div className="space-y-2 mb-2 max-h-80 overflow-y-auto pr-1">
                        {detectedVariables.map((name) => (
                            <div key={name} className="flex items-start gap-2">
                                <code className="text-xs pt-2 whitespace-nowrap">{`{{${name}}}`}</code>
                                {unfilledVariables.includes(name) && (
                                    <Tooltip title="No value set. The placeholder is sent as written.">
                                        <IconWarning className="text-warning mt-2 shrink-0" />
                                    </Tooltip>
                                )}
                                <LemonTextArea
                                    className="text-sm flex-1"
                                    placeholder="Value"
                                    value={getVariableValue(variableValues, name)}
                                    onChange={(value) => setVariableValue(name, value)}
                                    minRows={1}
                                    maxRows={6}
                                    data-attr="llma-playground-variable-value"
                                />
                            </div>
                        ))}
                    </div>
                )}
            </AnimatedCollapsible>
        </div>
    )
}

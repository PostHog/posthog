import { useActions, useValues } from 'kea'
import { Fragment } from 'react'

import { IconWarning } from '@posthog/icons'
import { LemonTag, LemonTextArea, Tooltip } from '@posthog/lemon-ui'

import { AnimatedCollapsible } from 'lib/components/AnimatedCollapsible'

import { CollapsibleChevronIcon } from './CollapsibleChevronIcon'
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
                {/* A plain button rather than a LemonButton: LemonButton paints
                    [aria-expanded='true'] with its active background, which reads as a
                    stuck grey state on an expanded section header */}
                <button
                    type="button"
                    onClick={() => toggleCollapsed('variables')}
                    aria-expanded={!collapsed}
                    data-attr="llma-playground-toggle-variables"
                    className="flex items-center gap-2 cursor-pointer text-sm font-semibold"
                >
                    <CollapsibleChevronIcon collapsed={collapsed} />
                    Variables{detectedVariables.length > 0 ? ` (${detectedVariables.length})` : ''}
                </button>
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
                    <div className="grid grid-cols-[auto_minmax(0,1fr)] gap-2 mb-2 max-h-80 overflow-y-auto pr-1">
                        {detectedVariables.map((name) => {
                            const unfilled = unfilledVariables.includes(name)
                            // The invisible icon keeps its slot, so filling a value never shifts the row.
                            const warningIcon = (
                                <span
                                    tabIndex={unfilled ? 0 : -1}
                                    role="img"
                                    aria-label="No value set"
                                    aria-hidden={!unfilled}
                                    className={`flex shrink-0 ${unfilled ? 'text-warning' : 'invisible'}`}
                                >
                                    <IconWarning />
                                </span>
                            )
                            return (
                                <Fragment key={name}>
                                    {/* h-10 matches LemonTextArea's 2.5rem min-height, centering the
                                        label and icon on the textarea's first row */}
                                    <div className="flex h-10 items-center gap-1.5 self-start">
                                        <code className="text-xs max-w-40 truncate" title={`{{${name}}}`}>
                                            {`{{${name}}}`}
                                        </code>
                                        {unfilled ? (
                                            <Tooltip title="No value set. The placeholder is sent as written.">
                                                {warningIcon}
                                            </Tooltip>
                                        ) : (
                                            warningIcon
                                        )}
                                    </div>
                                    <LemonTextArea
                                        className="text-sm"
                                        placeholder="Enter a test value"
                                        aria-label={`Value for {{${name}}}`}
                                        value={getVariableValue(variableValues, name)}
                                        onChange={(value) => setVariableValue(name, value)}
                                        minRows={1}
                                        maxRows={6}
                                        data-attr="llma-playground-variable-value"
                                    />
                                </Fragment>
                            )
                        })}
                    </div>
                )}
            </AnimatedCollapsible>
        </div>
    )
}

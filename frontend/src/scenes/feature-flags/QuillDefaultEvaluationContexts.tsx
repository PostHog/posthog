import { useId } from 'react'

import { IconBolt, IconPlus, IconX } from '@posthog/icons'
import { Button, Chip, ChipClose, Field, FieldLabel, Input, Switch, Text } from '@posthog/quill'

export function QuillDefaultEvaluationContexts({
    contexts,
    isEnabled,
    canAddMoreContexts,
    newContextInput,
    loading,
    isAdding,
    restrictedReason,
    onToggleEnabled,
    onNewContextInputChange,
    onKeyDown,
    onAdd,
    onStartAdding,
    onCancelAdding,
    onRemove,
}: {
    contexts: { id: number | string; name: string }[]
    isEnabled: boolean
    canAddMoreContexts: boolean
    newContextInput: string
    loading: boolean
    isAdding: boolean
    restrictedReason: string | null
    onToggleEnabled: (enabled: boolean) => void
    onNewContextInputChange: (value: string) => void
    onKeyDown: (e: React.KeyboardEvent) => void
    onAdd: () => void
    onStartAdding: () => void
    onCancelAdding: () => void
    onRemove: (name: string) => void
}): JSX.Element {
    const switchId = useId()

    return (
        <div className="flex flex-col gap-4">
            <Field orientation="horizontal" className="w-fit">
                <Switch
                    id={switchId}
                    data-attr="default-evaluation-contexts-switch"
                    checked={isEnabled}
                    onCheckedChange={onToggleEnabled}
                    disabled={loading}
                    disabledReason={restrictedReason}
                />
                <FieldLabel htmlFor={switchId}>Apply default evaluation contexts to new flags</FieldLabel>
            </Field>

            {isEnabled && (
                <div className="flex flex-col gap-2">
                    <div className="flex flex-wrap items-center gap-2">
                        {contexts.map((ctx) => (
                            <Chip key={ctx.id}>
                                <IconBolt />
                                {ctx.name}
                                <ChipClose
                                    aria-label={`Remove ${ctx.name}`}
                                    onClick={() => onRemove(ctx.name)}
                                    disabledReason={restrictedReason}
                                />
                            </Chip>
                        ))}

                        {isAdding ? (
                            <div className="inline-flex items-center gap-1">
                                <Input
                                    size="sm"
                                    value={newContextInput}
                                    onChange={(event) => onNewContextInputChange(event.target.value)}
                                    onKeyDown={onKeyDown}
                                    placeholder="e.g., main-app"
                                    aria-label="New evaluation context"
                                    autoFocus
                                    className="w-32"
                                    disabledReason={restrictedReason}
                                />
                                <Button
                                    variant="primary"
                                    size="icon"
                                    aria-label="Add context"
                                    tooltip="Add context"
                                    onClick={onAdd}
                                    disabled={!newContextInput.trim()}
                                    disabledReason={restrictedReason}
                                >
                                    <IconPlus />
                                </Button>
                                <Button
                                    size="icon"
                                    aria-label="Cancel"
                                    tooltip="Cancel"
                                    onClick={onCancelAdding}
                                    disabledReason={restrictedReason}
                                >
                                    <IconX />
                                </Button>
                            </div>
                        ) : (
                            canAddMoreContexts && (
                                <Button variant="outline" onClick={onStartAdding} disabledReason={restrictedReason}>
                                    <IconPlus />
                                    Add context
                                </Button>
                            )
                        )}
                    </div>

                    {contexts.length === 0 && !isAdding && (
                        <Text size="xs" variant="muted" render={<p className="m-0" />}>
                            No default evaluation contexts configured. Add contexts to automatically apply them to new
                            flags.
                        </Text>
                    )}

                    {contexts.length >= 10 && (
                        <Text size="xs" className="text-warning-foreground" render={<p className="m-0" />}>
                            Maximum of 10 default evaluation contexts allowed.
                        </Text>
                    )}
                </div>
            )}
        </div>
    )
}

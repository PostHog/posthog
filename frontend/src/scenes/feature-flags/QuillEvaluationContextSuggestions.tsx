import { IconUndo } from '@posthog/icons'
import { Chip, ChipClose, Heading, Text } from '@posthog/quill'

export function QuillEvaluationContextSuggestions({
    availableContexts,
    hiddenContexts,
    pendingContextName,
    actionDisabledReason,
    onHide,
    onUnhide,
}: {
    availableContexts: string[]
    hiddenContexts: string[]
    pendingContextName: string | null
    actionDisabledReason: string | null | undefined
    onHide: (name: string) => void
    onUnhide: (name: string) => void
}): JSX.Element {
    return (
        <div className="flex flex-col gap-4">
            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                These names are suggested when scoping a flag to evaluation contexts. Hiding a name only removes it from
                the suggestion list. Flags already using it keep working, and hidden names stay hidden until restored
                from this settings page.
            </Text>

            <div className="flex flex-col gap-2">
                <Heading size="sm" render={<h3 className="m-0" />}>
                    Suggested contexts
                </Heading>
                {availableContexts.length === 0 ? (
                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                        No suggested evaluation contexts.
                    </Text>
                ) : (
                    <div className="flex flex-wrap items-center gap-2">
                        {availableContexts.map((name) => (
                            <Chip key={name}>
                                {name}
                                <ChipClose
                                    aria-label={`Hide "${name}" from suggestions`}
                                    tooltip={`Hide "${name}" from suggestions`}
                                    onClick={() => onHide(name)}
                                    disabledReason={actionDisabledReason}
                                    loading={pendingContextName === name}
                                />
                            </Chip>
                        ))}
                    </div>
                )}
            </div>

            {hiddenContexts.length > 0 && (
                <div className="flex flex-col gap-2">
                    <Heading size="sm" render={<h3 className="m-0" />}>
                        Hidden from suggestions
                    </Heading>
                    <div className="flex flex-wrap items-center gap-2">
                        {hiddenContexts.map((name) => (
                            <Chip key={name} className="text-muted-foreground">
                                {name}
                                <ChipClose
                                    aria-label={`Restore "${name}" to suggestions`}
                                    tooltip="Restore to suggestions"
                                    onClick={() => onUnhide(name)}
                                    disabledReason={actionDisabledReason}
                                    loading={pendingContextName === name}
                                >
                                    <IconUndo />
                                </ChipClose>
                            </Chip>
                        ))}
                    </div>
                </div>
            )}
        </div>
    )
}

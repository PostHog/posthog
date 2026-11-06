import { IconCheck } from '@posthog/icons'
import { Card, CardGroup, CheckboxIndicator, Text, cn } from '@posthog/quill'

export interface Choice<T extends string> {
    value: T
    title: string
    description?: React.ReactNode
    icon?: JSX.Element
    /** Compact extra content at the end of the row, such as product icons. */
    trailing?: React.ReactNode
}

/**
 * Choice rows. An array `selected` makes it multi-select, with a checkbox on each row;
 * otherwise picking a row calls `onSelect`, and steps that auto-advance do it there.
 */
export function ChoiceList<T extends string>({
    choices,
    selected,
    onSelect,
    dataAttrPrefix,
    columns = 1,
}: {
    choices: Choice<T>[]
    selected: T | T[] | null
    onSelect: (value: T) => void
    dataAttrPrefix: string
    /** Two columns suit long lists of short choices. */
    columns?: 1 | 2
}): JSX.Element {
    const multiple = Array.isArray(selected)
    // CardGroup merges borders down one column; a grid keeps each card separate.
    const Container = columns === 2 ? TwoColumns : CardGroup

    return (
        <Container>
            {choices.map(({ value, title, description, icon, trailing }) => {
                const isSelected = multiple ? selected.includes(value) : selected === value
                return (
                    <Card key={value} size="sm" className="p-0">
                        <button
                            type="button"
                            role={multiple ? 'checkbox' : undefined}
                            aria-checked={multiple ? isSelected : undefined}
                            aria-pressed={multiple ? undefined : isSelected}
                            onClick={() => onSelect(value)}
                            data-attr={`${dataAttrPrefix}-${value}`}
                            className={cn(
                                'flex w-full min-w-0 cursor-pointer items-center gap-3 px-3 text-start hover:bg-fill-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/30',
                                columns === 2 ? 'py-2' : 'py-3',
                                isSelected && 'bg-fill-selected'
                            )}
                        >
                            {multiple && <CheckboxIndicator checked={isSelected} size="sm" />}
                            {icon && (
                                <span className="flex size-5 shrink-0 items-center justify-center text-lg">{icon}</span>
                            )}
                            <span className="flex min-w-0 flex-1 flex-col gap-1">
                                <Text size="sm" weight="medium" render={<span />}>
                                    {title}
                                </Text>
                                {description && (
                                    <Text size="xs" variant="muted" render={<span />}>
                                        {description}
                                    </Text>
                                )}
                            </span>
                            {trailing}
                            {!multiple && isSelected && <IconCheck className="size-4 shrink-0" />}
                        </button>
                    </Card>
                )
            })}
        </Container>
    )
}

function TwoColumns({ children }: { children: React.ReactNode }): JSX.Element {
    return <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">{children}</div>
}

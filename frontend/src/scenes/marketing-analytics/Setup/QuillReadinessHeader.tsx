import { useId } from 'react'

import { Button, Item, ItemContent, ItemDescription, Progress, Skeleton, Text } from '@posthog/quill'

export interface QuillReadinessChip {
    key: string
    label: string
    statusLabel: string
    what: string | undefined
    explanation: string
    ready: boolean
    blockerCount: number
    focused: boolean
    onFocus: () => void
}

export function QuillReadinessHeader({
    loading,
    chips,
    unlocked,
    degraded,
    truncated,
}: {
    loading: boolean
    chips: QuillReadinessChip[]
    unlocked: number
    degraded: string[]
    truncated: boolean
}): JSX.Element {
    const headingId = useId()

    if (loading) {
        return (
            <div className="flex flex-col gap-2">
                <Skeleton className="h-4 w-64" />
                <Skeleton className="h-8 w-full" />
            </div>
        )
    }

    const total = chips.length

    return (
        <div className="flex flex-col gap-3">
            {total > 0 && (
                <div className="flex flex-col gap-2">
                    <div className="flex flex-wrap items-baseline gap-2">
                        <Text
                            id={headingId}
                            size="xs"
                            variant="muted"
                            weight="semibold"
                            render={<span className="m-0 uppercase tracking-wide" />}
                        >
                            What you can measure right now
                        </Text>
                        <Text size="xs" variant="muted" render={<span className="m-0" />}>
                            {unlocked} of {total} ready
                        </Text>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                        {chips.map((chip) => {
                            const clickable = chip.blockerCount > 0
                            return (
                                <Button
                                    key={chip.key}
                                    variant="outline"
                                    // Guarded click rather than disabled, which would drop the chip out of
                                    // the tab order and leave its tooltip with no keyboard path.
                                    onClick={clickable ? chip.onFocus : undefined}
                                    aria-pressed={clickable ? chip.focused : undefined}
                                    aria-label={`${chip.label} · ${chip.statusLabel}`}
                                    className={
                                        chip.focused ? 'bg-fill-selected' : clickable ? undefined : 'cursor-default'
                                    }
                                    tooltip={
                                        <div className="flex max-w-xs flex-col gap-1">
                                            <span className="font-semibold">
                                                {chip.label} · {chip.statusLabel}
                                            </span>
                                            {chip.what && <span>{chip.what}</span>}
                                            <span>{chip.explanation}</span>
                                            {clickable && (
                                                <span>
                                                    Click to show the {chip.blockerCount} suggestion
                                                    {chip.blockerCount === 1 ? '' : 's'} that would change this.
                                                </span>
                                            )}
                                        </div>
                                    }
                                >
                                    <span className={chip.ready || chip.focused ? undefined : 'text-muted-foreground'}>
                                        {chip.label}
                                    </span>
                                    {clickable && (
                                        <span
                                            className="text-xs text-muted-foreground tabular-nums"
                                            aria-label={`${chip.blockerCount} suggestions`}
                                        >
                                            {chip.blockerCount}
                                        </span>
                                    )}
                                </Button>
                            )
                        })}
                    </div>
                    <Progress value={(unlocked / total) * 100} aria-labelledby={headingId} />
                </div>
            )}

            {degraded.length > 0 && (
                <Item tone="warning" size="sm">
                    <ItemContent>
                        <ItemDescription>
                            Some checks could not run ({degraded.join(', ')}), so this list is incomplete. Reload to try
                            again.
                        </ItemDescription>
                    </ItemContent>
                </Item>
            )}
            {truncated && (
                <Item tone="info" size="sm">
                    <ItemContent>
                        <ItemDescription>
                            You have more campaigns or UTM values than we analyse in one pass, so the figures below are
                            approximate — they cover your highest-spend campaigns and highest-volume UTM values.
                        </ItemDescription>
                    </ItemContent>
                </Item>
            )}
        </div>
    )
}

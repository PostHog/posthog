import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'

import { IconArrowRight, IconDrag } from '@posthog/icons'
import { Button, ButtonGroup, cn } from '@posthog/quill'

import { TODAY_PANES } from './todayRailItems'
import { TodayRailPaneCheckbox } from './TodayRailPaneCheckbox'
import type { TodayRailPane } from './todayShellLogic'

/** One pane in the Customize navigation list. Only the handle starts a drag, so the checkbox takes plain clicks. */
export function TodayCustomizeRailRow({
    pane,
    shown,
    isFirst,
    isLast,
    onToggle,
    onMoveUp,
    onMoveDown,
}: {
    pane: TodayRailPane
    shown: boolean
    isFirst: boolean
    isLast: boolean
    onToggle: () => void
    onMoveUp: () => void
    onMoveDown: () => void
}): JSX.Element {
    const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } = useSortable({
        id: pane,
    })
    const { label } = TODAY_PANES[pane]

    return (
        <div
            ref={setNodeRef}
            // eslint-disable-next-line react/forbid-dom-props
            style={{ transform: CSS.Translate.toString(transform), transition }}
            className={cn('group/row relative flex items-center gap-2', isDragging && 'z-10 opacity-60')}
        >
            <span
                ref={setActivatorNodeRef}
                {...attributes}
                {...listeners}
                aria-label={`Drag ${label} to reorder`}
                className="flex w-5 cursor-grab touch-none justify-center text-muted-foreground opacity-0 group-hover/row:opacity-100 group-has-[:focus-visible]/row:opacity-100 [&_svg]:size-4"
            >
                <IconDrag />
            </span>
            <TodayRailPaneCheckbox pane={pane} checked={shown} onToggle={onToggle} />
            {/* Hover or keyboard focus shows the arrows. A click's focus does not, so they hide again once the pointer leaves. */}
            <ButtonGroup className="ms-auto shrink-0 opacity-0 group-hover/row:opacity-100 group-has-[:focus-visible]/row:opacity-100">
                <Button
                    variant="outline"
                    size="icon-sm"
                    aria-label={`Move ${label} up`}
                    disabledReason={isFirst ? `${label} is already first` : undefined}
                    onClick={onMoveUp}
                >
                    <IconArrowRight className="-rotate-90" />
                </Button>
                <Button
                    variant="outline"
                    size="icon-sm"
                    aria-label={`Move ${label} down`}
                    disabledReason={isLast ? `${label} is already last` : undefined}
                    onClick={onMoveDown}
                >
                    <IconArrowRight className="rotate-90" />
                </Button>
            </ButtonGroup>
        </div>
    )
}

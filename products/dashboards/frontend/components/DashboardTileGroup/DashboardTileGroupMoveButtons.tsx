import clsx from 'clsx'

import { IconArrowLeft, IconArrowRight } from '@posthog/icons'

import { IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

import type { TileGroupDisplay } from '~/types'

import type { TileGroupMoveDirection, TileGroupMoveDirections } from '../../dashboardTileSections'

export interface TileGroupMoveActions extends TileGroupMoveDirections {
    onMove: (direction: TileGroupMoveDirection) => void
}

const MOVE_BUTTONS: Record<
    TileGroupDisplay,
    { noun: string } & Record<TileGroupMoveDirection, { label: string; icon: JSX.Element }>
> = {
    sections: {
        noun: 'group',
        up: { label: 'Move up', icon: <IconArrowUp /> },
        down: { label: 'Move down', icon: <IconArrowDown /> },
    },
    tabs: {
        noun: 'tab',
        up: { label: 'Move left', icon: <IconArrowLeft /> },
        down: { label: 'Move right', icon: <IconArrowRight /> },
    },
}

interface DashboardTileGroupMoveButtonsProps {
    groupDisplay: TileGroupDisplay
    moveActions: TileGroupMoveActions
    groupHasTiles: boolean
    className?: string
}

/** Reorder buttons for a group header or tab bar. The caller decides when they show, usually on hover. */
export function DashboardTileGroupMoveButtons({
    groupDisplay,
    moveActions,
    groupHasTiles,
    className,
}: DashboardTileGroupMoveButtonsProps): JSX.Element {
    const { noun, ...buttons } = MOVE_BUTTONS[groupDisplay]
    // A group's place comes from its tiles' rows, so a group with no tiles has no place to change.
    const disabledReason = (direction: TileGroupMoveDirection): string | undefined =>
        !groupHasTiles
            ? `Add a tile to this ${noun} before you move it`
            : !moveActions[direction === 'up' ? 'canMoveUp' : 'canMoveDown']
              ? `This ${noun} is already ${direction === 'up' ? 'first' : 'last'}`
              : undefined

    return (
        <div className={clsx('flex shrink-0 items-center gap-0.5', className)}>
            {(['up', 'down'] as const).map((direction) => (
                <LemonButton
                    key={direction}
                    size="small"
                    icon={buttons[direction].icon}
                    tooltip={buttons[direction].label}
                    aria-label={buttons[direction].label}
                    onClick={() => moveActions.onMove(direction)}
                    disabledReason={disabledReason(direction)}
                    data-attr={`dashboard-tile-group-move-${direction}`}
                />
            ))}
        </div>
    )
}

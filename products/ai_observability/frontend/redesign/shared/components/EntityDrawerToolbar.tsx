import { ReactNode } from 'react'

import { IconChevronDown, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { KeyboardShortcut } from 'lib/lemon-ui/KeyboardShortcut/KeyboardShortcut'

export interface EntityDrawerPosition {
    index: number
    total: number
}

export interface EntityDrawerToolbarProps {
    /** Singular and lowercase: "error", "tool", "person". */
    noun: string
    title: ReactNode
    position: EntityDrawerPosition | null
    onPrevious: (() => void) | null
    onNext: (() => void) | null
    onClose: () => void
    'data-attr': string
}

export function EntityDrawerToolbar({
    noun,
    title,
    position,
    onPrevious,
    onNext,
    onClose,
    'data-attr': dataAttr,
}: EntityDrawerToolbarProps): JSX.Element {
    return (
        <div className="flex min-w-0 flex-1 items-center gap-1">
            <LemonButton
                size="small"
                icon={<IconChevronDown className="rotate-180" />}
                tooltip={`Previous ${noun}`}
                aria-label={`Previous ${noun}`}
                onClick={onPrevious ?? undefined}
                disabledReason={onPrevious ? undefined : `This is the first ${noun}`}
                data-attr={`${dataAttr}-previous`}
            />
            <LemonButton
                size="small"
                icon={<IconChevronDown />}
                tooltip={`Next ${noun}`}
                aria-label={`Next ${noun}`}
                onClick={onNext ?? undefined}
                disabledReason={onNext ? undefined : `This is the last ${noun}`}
                data-attr={`${dataAttr}-next`}
            />
            {position ? (
                <span className="ml-1 whitespace-nowrap text-xs text-secondary" aria-live="polite">
                    {`${position.index + 1} of ${position.total}`}
                </span>
            ) : null}
            <div className="ml-2 min-w-0 flex-1 truncate font-semibold">{title}</div>
            <LemonButton
                size="small"
                icon={<IconX />}
                tooltip={
                    <>
                        Close <KeyboardShortcut escape />
                    </>
                }
                aria-label="Close"
                onClick={onClose}
                data-attr={`${dataAttr}-close`}
            />
        </div>
    )
}

import clsx from 'clsx'
import { useRef, useState } from 'react'

import { RawInputAutosize } from 'lib/lemon-ui/LemonInput/RawInputAutosize'

interface DashboardTileGroupTitleInputProps {
    initialTitle: string
    placeholder: string
    onSave: (title: string) => void
    onDone: () => void
    className?: string
}

/** Renames a group or tab in place. Leaving the field saves, Escape cancels. */
export function DashboardTileGroupTitleInput({
    initialTitle,
    placeholder,
    onSave,
    onDone,
    className,
}: DashboardTileGroupTitleInputProps): JSX.Element {
    const [value, setValue] = useState(initialTitle)
    const cancelled = useRef(false)

    return (
        <RawInputAutosize
            autoFocus
            value={value}
            placeholder={placeholder}
            maxLength={200}
            // No padding or border, so the field takes the label's exact size. The outline does not take space.
            className={clsx(
                'm-0 -mr-0.5 rounded border-0 bg-transparent p-0 font-[inherit] text-[length:inherit] leading-[inherit] text-inherit outline outline-1 outline-offset-2 outline-accent placeholder:text-secondary',
                className
            )}
            onChange={(event) => setValue(event.currentTarget.value)}
            onFocus={(event) => event.currentTarget.select()}
            // A tab label sits inside the tab button, so keys and clicks must not reach it.
            onClick={(event) => event.stopPropagation()}
            onKeyDown={(event) => {
                event.stopPropagation()
                if (event.key === 'Enter') {
                    event.currentTarget.blur()
                } else if (event.key === 'Escape') {
                    cancelled.current = true
                    event.currentTarget.blur()
                }
            }}
            onBlur={() => {
                if (!cancelled.current && value.trim() !== initialTitle.trim()) {
                    onSave(value)
                }
                onDone()
            }}
            data-attr="dashboard-tile-group-title-input"
        />
    )
}

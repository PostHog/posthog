import { ReactElement } from 'react'

/**
 * Replay-style trigger for the rebuilt taxonomic menu: a LemonInput search box
 * with a leading filter-icon button. Focusing/typing in the box opens the
 * combobox; clicking the icon opens the dropdown menu.
 *
 * LemonInput (not quill) so the trigger matches the surrounding scene's UI. The
 * combobox internals stay quill; when it opens, the popover panel renders its
 * own live search field (header above, list below) positioned over this row, so
 * here we render an invisible same-height spacer to hold the anchor in place
 * and avoid a layout shift behind the panel.
 */
import { LemonInput } from 'lib/lemon-ui/LemonInput'

export interface MenuInputTriggerProps {
    iconButton: ReactElement
    placeholder?: string
    value?: string
    onChange?: (value: string) => void
    onFocus?: () => void
    fullWidth?: boolean
    /** While the combobox panel is open it owns the visible field; the row
     *  holds an invisible spacer so the trigger anchor and layout don't shift. */
    spacerOnly?: boolean
}

export function MenuInputTrigger({
    iconButton,
    placeholder,
    value,
    onChange,
    onFocus,
    fullWidth = true,
    spacerOnly = false,
}: MenuInputTriggerProps): JSX.Element {
    if (spacerOnly) {
        return (
            <div aria-hidden="true">
                <LemonInput
                    fullWidth={fullWidth}
                    size="small"
                    disabled
                    placeholder={placeholder}
                    className="invisible"
                />
            </div>
        )
    }
    return (
        <LemonInput
            fullWidth={fullWidth}
            size="small"
            prefix={iconButton}
            data-attr="taxonomic-filter-menu-input"
            placeholder={placeholder}
            value={value}
            onChange={onChange}
            onFocus={onFocus}
        />
    )
}

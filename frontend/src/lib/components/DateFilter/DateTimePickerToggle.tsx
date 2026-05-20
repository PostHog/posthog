import { useActions, useValues } from 'kea'

import { IconClockRewind, IconFlask } from '@posthog/icons'

import { Tooltip } from 'lib/lemon-ui/Tooltip/Tooltip'

import { dateTimePickerPreferenceLogic } from './dateTimePickerPreferenceLogic'

/**
 * Floating corner badge rendered over the DateFilter trigger wherever the
 * `datetime-picker-rebuild` flag is on. Flips the global
 * `dateTimePickerPreferenceLogic` so the user can opt in/out of the rebuilt
 * Quill picker everywhere at once.
 *
 * Positioned `absolute` inside the trigger's top-right corner — the parent
 * must be `relative`. Kept inside the trigger box (no negative offset) so
 * an `overflow-hidden` ancestor can't clip it.
 */
export function DateTimePickerToggle(): JSX.Element {
    const { useNewPicker } = useValues(dateTimePickerPreferenceLogic)
    const { setUseNewPicker } = useActions(dateTimePickerPreferenceLogic)

    const label = useNewPicker ? 'Switch to the classic date picker' : 'Switch to the new date picker'

    return (
        <Tooltip title={label}>
            <button
                type="button"
                aria-label={label}
                data-attr="datetime-picker-toggle"
                onClick={(e) => {
                    e.preventDefault()
                    e.stopPropagation()
                    setUseNewPicker(!useNewPicker)
                }}
                className="absolute top-0 right-0 z-10 flex size-3.5 items-center justify-center rounded-full rounded-tr-sm border border-accent bg-surface-primary text-accent shadow-sm transition-opacity hover:opacity-70"
            >
                {useNewPicker ? <IconClockRewind className="size-2.5" /> : <IconFlask className="size-2.5" />}
            </button>
        </Tooltip>
    )
}

import { actions, kea, listeners, path, reducers } from 'kea'
import posthog from 'posthog-js'

import type { dateTimePickerPreferenceLogicType } from './dateTimePickerPreferenceLogicType'

/**
 * Global, persisted preference for which date/time range picker to render
 * wherever the `datetime-picker-rebuild` flag is enabled.
 *
 * Defaults to the rebuilt Quill picker; the toggle in `DateTimePickerToggle`
 * lets a user opt back to the classic LemonCalendarRange (and forward
 * again). One logic instance, so flipping it anywhere flips every picker
 * at once.
 */
export const dateTimePickerPreferenceLogic = kea<dateTimePickerPreferenceLogicType>([
    path(['lib', 'components', 'DateFilter', 'dateTimePickerPreferenceLogic']),
    actions({
        setUseNewPicker: (useNewPicker: boolean) => ({ useNewPicker }),
    }),
    reducers({
        useNewPicker: [
            true,
            { persist: true },
            {
                setUseNewPicker: (_, { useNewPicker }) => useNewPicker,
            },
        ],
    }),
    listeners(() => ({
        setUseNewPicker: ({ useNewPicker }) => {
            posthog.capture('datetime picker preference changed', { useNewPicker })
        },
    })),
])

import { actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import type { sceneTitleEditorLogicType } from './sceneTitleEditorLogicType'

export interface SceneTitleEditorLogicProps {
    /** Unique identifier for this editor instance (e.g., 'dashboard-123-name') */
    id: string
    /** Callback to persist the value */
    onChange?: (value: string) => void
    /** Debounce time in ms */
    debounceMs?: number
    /** If true, only saves on blur (not on every change) */
    saveOnBlur?: boolean
}

export const sceneTitleEditorLogic = kea<sceneTitleEditorLogicType>([
    path(['layout', 'scenes', 'components', 'sceneTitleEditorLogic']),
    props({} as SceneTitleEditorLogicProps),
    key((props) => props.id),

    actions({
        /** Set the value from user input */
        setValue: (value: string) => ({ value }),
        /** Called when prop value changes - listener will decide whether to sync */
        onPropValueChange: (value: string) => ({ value }),
        /** Internal: sync value from persisted (only called when not editing) */
        syncValue: (value: string) => ({ value }),
        /** Set editing state */
        setIsEditing: (isEditing: boolean) => ({ isEditing }),
        /** Trigger save with debounce (for non-saveOnBlur mode) */
        triggerDebouncedSave: (value: string) => ({ value }),
        /** Trigger save on blur (for saveOnBlur mode) */
        triggerBlurSave: (value: string) => ({ value }),
        /** Actually persist the value */
        persistValue: (value: string) => ({ value }),
    }),

    reducers({
        /** The current value being edited (local state) */
        value: [
            '' as string,
            {
                setValue: (_, { value }) => value,
                syncValue: (_, { value }) => value,
            },
        ],
        /** Whether the user is actively editing */
        isEditing: [
            false,
            {
                setIsEditing: (_, { isEditing }) => isEditing,
            },
        ],
        /** The last persisted value (from props) - always tracks prop */
        persistedValue: [
            '' as string,
            {
                onPropValueChange: (_, { value }) => value,
            },
        ],
    }),

    selectors({
        hasUnsavedChanges: [
            (s) => [s.value, s.persistedValue],
            (value, persistedValue) => value !== persistedValue,
        ],
    }),

    listeners(({ actions, values, props }) => ({
        triggerDebouncedSave: async ({ value }, breakpoint) => {
            // Use Kea breakpoint for debouncing - cancels previous pending saves
            await breakpoint(props.debounceMs ?? 100)
            actions.persistValue(value)
        },
        triggerBlurSave: async ({ value }, breakpoint) => {
            // Small debounce for blur saves to handle rapid blur/focus events
            await breakpoint(props.debounceMs ?? 100)
            actions.persistValue(value)
        },
        persistValue: ({ value }) => {
            if (props.onChange) {
                props.onChange(value)
            }
        },
        setValue: ({ value }) => {
            // Only trigger debounced save if NOT in saveOnBlur mode
            if (!props.saveOnBlur) {
                actions.triggerDebouncedSave(value)
            }
        },
        onPropValueChange: ({ value }) => {
            // Only sync to local value if NOT currently editing
            if (!values.isEditing) {
                actions.syncValue(value)
            }
            // persistedValue is always updated via reducer
        },
    })),
])

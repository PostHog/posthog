import { actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { useActions, useValues } from 'kea'
import { useEffect, useId } from 'react'

import type { sceneTitleLogicType } from './sceneTitleLogicType'

export interface SceneTitleLogicProps {
    /** Unique key for this logic instance */
    key: string
    onChange?: (value: string) => void
    debounceMs?: number
}

export const sceneTitleLogic = kea<sceneTitleLogicType>([
    path((key) => ['layout', 'scenes', 'components', 'sceneTitleLogic', key]),
    props({} as SceneTitleLogicProps),
    key((props) => props.key),
    actions({
        setValue: (value: string) => ({ value }),
        setIsEditing: (isEditing: boolean) => ({ isEditing }),
        syncFromProp: (value: string) => ({ value }),
        triggerDebouncedSave: (value: string) => ({ value }),
        executeSave: (value: string) => ({ value }),
        markSaved: (value: string) => ({ value }),
    }),
    reducers({
        localValue: [
            '' as string,
            {
                setValue: (_, { value }) => value,
                syncFromProp: (state, { value }) => value ?? state,
            },
        ],
        isEditing: [
            false,
            {
                setIsEditing: (_, { isEditing }) => isEditing,
            },
        ],
        lastSavedValue: [
            '' as string,
            {
                syncFromProp: (_, { value }) => value ?? '',
                markSaved: (_, { value }) => value,
            },
        ],
        pendingSaveValue: [
            null as string | null,
            {
                triggerDebouncedSave: (_, { value }) => value,
                executeSave: () => null,
                markSaved: () => null,
            },
        ],
    }),
    selectors({
        isDirty: [
            (s) => [s.localValue, s.lastSavedValue, s.pendingSaveValue],
            (localValue, lastSavedValue, pendingSaveValue) =>
                localValue !== lastSavedValue || pendingSaveValue !== null,
        ],
        shouldSyncFromProp: [
            (s) => [s.isEditing, s.pendingSaveValue],
            (isEditing, pendingSaveValue) => !isEditing && pendingSaveValue === null,
        ],
    }),
    listeners(({ actions, values, props }) => ({
        triggerDebouncedSave: async ({ value }, breakpoint) => {
            // Use Kea breakpoint for debouncing - this cancels pending saves if called again
            await breakpoint(props.debounceMs ?? 1000)
            actions.executeSave(value)
        },
        executeSave: ({ value }) => {
            if (props.onChange && value !== values.lastSavedValue) {
                props.onChange(value)
                actions.markSaved(value)
            }
        },
    })),
])

interface UseSceneTitleEditingOptions {
    initialValue: string | undefined | null
    onChange?: (value: string) => void
    debounceMs?: number
    saveOnBlur?: boolean
    forceEdit?: boolean
    isLoading?: boolean
}

interface UseSceneTitleEditingResult {
    value: string
    isEditing: boolean
    setIsEditing: (editing: boolean) => void
    handleChange: (newValue: string) => void
    handleBlur: () => void
}

export function useSceneTitleEditing({
    initialValue,
    onChange,
    debounceMs = 1000,
    saveOnBlur = false,
    forceEdit = false,
    isLoading = false,
}: UseSceneTitleEditingOptions): UseSceneTitleEditingResult {
    const uniqueId = useId()
    const logicKey = `scene-title-${uniqueId}`

    const logic = sceneTitleLogic({ key: logicKey, onChange, debounceMs })
    const { localValue, isEditing, shouldSyncFromProp } = useValues(logic)
    const { setValue, setIsEditing, syncFromProp, triggerDebouncedSave, executeSave } = useActions(logic)

    // Sync from prop when allowed (not editing and no pending save)
    useEffect(() => {
        if (!isLoading && shouldSyncFromProp) {
            syncFromProp(initialValue ?? '')
        }
    }, [initialValue, isLoading, shouldSyncFromProp, syncFromProp])

    // Handle forceEdit changes
    useEffect(() => {
        if (!isLoading) {
            setIsEditing(forceEdit)
        }
    }, [forceEdit, isLoading, setIsEditing])

    const handleChange = (newValue: string): void => {
        setValue(newValue)
        if (!saveOnBlur) {
            triggerDebouncedSave(newValue)
        }
    }

    const handleBlur = (): void => {
        if (saveOnBlur && localValue !== (initialValue ?? '')) {
            // For saveOnBlur mode, save immediately on blur
            executeSave(localValue)
        }
        if (!forceEdit) {
            setIsEditing(false)
        }
    }

    return {
        value: localValue,
        isEditing,
        setIsEditing,
        handleChange,
        handleBlur,
    }
}

import { useEffect, useRef, useState } from 'react'
import { useDebouncedCallback } from 'use-debounce'

export interface SceneNameEditingOptions {
    name?: string
    isLoading?: boolean
    onChange?: (value: string) => void
    forceEdit?: boolean
    renameDebounceMs?: number
    saveOnBlur?: boolean
    isGeneratingMetadata?: boolean
}

export interface SceneNameEditing {
    name: string | undefined
    isEditing: boolean
    /** Wraps the field and its controls, so moving focus between them does not end the edit. */
    containerRef: React.RefObject<HTMLDivElement>
    startEditing: () => void
    change: (value: string) => void
    blur: (event: React.FocusEvent) => void
    saveFromEnter: (value: string) => void
    /**
     * Leaves the field. With `saveOnBlur` it also drops the unsaved value. Without it every keystroke has already
     * been saved, so there is nothing local to drop.
     */
    cancel: () => void
}

export function useSceneNameEditing({
    name: initialName,
    isLoading = false,
    onChange,
    forceEdit = false,
    renameDebounceMs = 100,
    saveOnBlur = false,
    isGeneratingMetadata = false,
}: SceneNameEditingOptions): SceneNameEditing {
    const [name, setName] = useState(initialName)
    const [prevInitialName, setPrevInitialName] = useState(initialName)
    // Mirror of the value currently held in the local field. Lets us tell a genuine
    // external update (loading a resource, an AI-generated name) apart from an echo of
    // the user's own edit arriving back through the form, so the render-phase
    // reconciliation below can't overwrite a keystroke that hasn't round-tripped yet.
    const latestNameRef = useRef(initialName)
    // What the last Enter press saved, held only until the next blur. `initialName` catches up
    // when the save round-trips, so the blur straight after Enter still sees a changed field and
    // would save the same value a second time.
    const savedByEnterRef = useRef<string | null>(null)
    // Set by Escape, so the blur that follows does not save the value the user just dropped.
    const cancelledRef = useRef(false)
    if (initialName !== prevInitialName) {
        setPrevInitialName(initialName)
        if (initialName !== latestNameRef.current) {
            setName(initialName)
            latestNameRef.current = initialName
        }
    }

    const [isEditing, setIsEditing] = useState(forceEdit)
    const containerRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        if (!isLoading && forceEdit) {
            setIsEditing(true)
        } else {
            setIsEditing(false)
        }
    }, [isLoading, forceEdit])

    const debouncedOnBlurSave = useDebouncedCallback((value: string) => {
        onChange?.(value)
    }, renameDebounceMs)

    const debouncedOnChange = useDebouncedCallback((value: string) => {
        onChange?.(value)
    }, renameDebounceMs)

    useEffect(() => {
        return () => {
            debouncedOnBlurSave.flush()
            debouncedOnChange.flush()
        }
    }, [debouncedOnBlurSave, debouncedOnChange])

    const startEditing = (): void => {
        if (!isGeneratingMetadata) {
            cancelledRef.current = false
            setIsEditing(true)
        }
    }

    const change = (value: string): void => {
        latestNameRef.current = value
        setName(value)
        if (forceEdit && !saveOnBlur) {
            onChange?.(value)
        } else if (!saveOnBlur) {
            debouncedOnChange(value)
        }
    }

    const blur = (event: React.FocusEvent): void => {
        const relatedTarget = event.relatedTarget as HTMLElement | null
        if (relatedTarget && containerRef.current && containerRef.current.contains(relatedTarget)) {
            return
        }
        const savedByEnter = savedByEnterRef.current
        savedByEnterRef.current = null
        if (cancelledRef.current) {
            cancelledRef.current = false
        } else if (saveOnBlur && !isGeneratingMetadata && name !== initialName && name !== savedByEnter) {
            debouncedOnBlurSave(name || '')
        } else if (!saveOnBlur) {
            // Commit any pending debounced change synchronously so a submit or
            // validation that immediately follows blur reads the value the user sees.
            debouncedOnChange.flush()
        }
        if (!forceEdit) {
            setIsEditing(false)
        }
    }

    const saveFromEnter = (value: string): void => {
        if (saveOnBlur && value !== initialName) {
            savedByEnterRef.current = value || ''
            onChange?.(value || '')
        }
    }

    const cancel = (): void => {
        if (saveOnBlur) {
            cancelledRef.current = true
            latestNameRef.current = initialName
            setName(initialName)
        }
        if (!forceEdit) {
            setIsEditing(false)
        }
    }

    return { name, isEditing, containerRef, startEditing, change, blur, saveFromEnter, cancel }
}

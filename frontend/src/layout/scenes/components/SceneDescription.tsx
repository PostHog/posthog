import { useEffect, useRef, useState } from 'react'
import { useDebouncedCallback } from 'use-debounce'

import { IconPencil } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { ButtonPrimitive, buttonPrimitiveVariants } from 'lib/ui/Button/ButtonPrimitives'
import { TextareaPrimitive } from 'lib/ui/TextareaPrimitive/TextareaPrimitive'
import { WrappingLoadingSkeleton } from 'lib/ui/WrappingLoadingSkeleton/WrappingLoadingSkeleton'
import { cn } from 'lib/utils/css-classes'

type SceneDescriptionProps = {
    description?: string | null
    markdown?: boolean
    isLoading?: boolean
    onChange?: (value: string) => void
    canEdit?: boolean
    forceEdit?: boolean
    renameDebounceMs?: number
    saveOnBlur?: boolean
    maxLength?: number
    /** When true, description field is read-only (title AI control may be generating body copy too). */
    isGeneratingMetadata?: boolean
}

export function SceneDescription({
    description: initialDescription,
    markdown = false,
    isLoading = false,
    onChange,
    canEdit = false,
    forceEdit = false,
    renameDebounceMs = 100,
    saveOnBlur = false,
    maxLength,
    isGeneratingMetadata = false,
}: SceneDescriptionProps): JSX.Element | null {
    const [description, setDescription] = useState(initialDescription)
    const [prevInitialDescription, setPrevInitialDescription] = useState(initialDescription)
    // See SceneName: keep external updates from clobbering an in-flight local edit.
    const latestDescriptionRef = useRef(initialDescription)
    if (initialDescription !== prevInitialDescription) {
        setPrevInitialDescription(initialDescription)
        if (initialDescription !== latestDescriptionRef.current) {
            setDescription(initialDescription)
            latestDescriptionRef.current = initialDescription
        }
    }

    const [isEditing, setIsEditing] = useState(forceEdit)

    const textClasses = 'text-sm my-0 select-auto'

    const emptyText = canEdit ? 'Enter description (optional)' : 'No description'

    useEffect(() => {
        if (!isLoading && forceEdit) {
            setIsEditing(true)
        } else {
            setIsEditing(false)
        }
    }, [isLoading, forceEdit])

    const debouncedOnBlurSaveDescription = useDebouncedCallback((value: string) => {
        onChange?.(value)
    }, renameDebounceMs)

    const debouncedOnDescriptionChange = useDebouncedCallback((value: string) => {
        onChange?.(value)
    }, renameDebounceMs)

    useEffect(() => {
        return () => {
            debouncedOnBlurSaveDescription.flush()
            debouncedOnDescriptionChange.flush()
        }
    }, [debouncedOnBlurSaveDescription, debouncedOnDescriptionChange])

    const handleBlur = (): void => {
        if (saveOnBlur && !isGeneratingMetadata && description !== initialDescription) {
            debouncedOnBlurSaveDescription(description || '')
        } else if (!saveOnBlur) {
            debouncedOnDescriptionChange.flush()
        }
        if (!forceEdit) {
            setIsEditing(false)
        }
    }

    const Element =
        onChange && canEdit ? (
            <>
                {isEditing ? (
                    <TextareaPrimitive
                        variant="default"
                        name="description"
                        value={description || ''}
                        maxLength={maxLength}
                        readOnly={isGeneratingMetadata}
                        onChange={(e) => {
                            latestDescriptionRef.current = e.target.value
                            setDescription(e.target.value)
                            if (forceEdit && !saveOnBlur) {
                                onChange?.(e.target.value)
                            } else if (!saveOnBlur) {
                                debouncedOnDescriptionChange(e.target.value)
                            }
                        }}
                        data-attr="scene-description-textarea"
                        className={cn(
                            buttonPrimitiveVariants({
                                inert: true,
                                className: `${textClasses} w-full hover:bg-fill-input px-[var(--button-padding-x-sm)]`,
                                autoHeight: true,
                            }),
                            '[&_.LemonIcon]:size-4 input-like',
                            isGeneratingMetadata && 'cursor-not-allowed opacity-80'
                        )}
                        wrapperClassName="w-full"
                        markdown={markdown}
                        placeholder={emptyText}
                        onBlur={handleBlur}
                        autoFocus={!forceEdit}
                    />
                ) : (
                    <Tooltip
                        title={
                            isGeneratingMetadata
                                ? 'Finish generating before editing'
                                : canEdit && !forceEdit
                                  ? 'Edit description'
                                  : undefined
                        }
                        placement="bottom"
                        arrowOffset={10}
                    >
                        <ButtonPrimitive
                            onClick={() => {
                                if (!isGeneratingMetadata) {
                                    setIsEditing(true)
                                }
                            }}
                            disabled={isGeneratingMetadata}
                            className="flex text-start px-[var(--button-padding-x-sm)] py-[var(--button-padding-y-base)] [&_.LemonIcon]:size-4 focus-visible:z-20"
                            autoHeight
                            size="base"
                        >
                            <LemonMarkdown lowKeyHeadings>
                                {description || (canEdit ? 'Enter description (optional)' : 'No description')}
                            </LemonMarkdown>
                            {canEdit && !forceEdit && <IconPencil />}
                        </ButtonPrimitive>
                    </Tooltip>
                )}
            </>
        ) : (
            <>
                {markdown && description !== null && description !== undefined ? (
                    <LemonMarkdown
                        lowKeyHeadings
                        className={buttonPrimitiveVariants({
                            inert: true,
                            className: `${textClasses} block px-[var(--button-padding-x-sm)]`,
                            autoHeight: true,
                        })}
                    >
                        {description}
                    </LemonMarkdown>
                ) : (
                    <p
                        className={buttonPrimitiveVariants({
                            inert: true,
                            className: `${textClasses} px-[var(--button-padding-x-sm)]`,
                            autoHeight: true,
                        })}
                    >
                        {description !== null ? description : <span className="text-tertiary">{emptyText}</span>}
                    </p>
                )}
            </>
        )

    if (isLoading) {
        return (
            <div className="w-full">
                <WrappingLoadingSkeleton fullWidth>{Element}</WrappingLoadingSkeleton>
            </div>
        )
    }

    return (
        <div className="scene-description relative focus-within:z-20">
            <div className="-mx-[var(--button-padding-x-sm)] flex items-center gap-0">{Element}</div>
        </div>
    )
}

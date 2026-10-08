import type { ReactNode } from 'react'

import { IconSparkles } from '@posthog/icons'
import { Button, Input, SkeletonText, Tooltip, TooltipContent, TooltipTrigger, cn } from '@posthog/quill'

import { useSceneNameEditing } from './useSceneNameEditing'

export interface QuillSceneNameProps {
    name?: string
    isLoading?: boolean
    onChange?: (value: string) => void
    canEdit?: boolean
    /** Keeps the field open, for a resource that has no name yet. */
    forceEdit?: boolean
    renameDebounceMs?: number
    saveOnBlur?: boolean
    onGenerateMetadata?: () => void
    isGeneratingMetadata?: boolean
    suffix?: ReactNode
    editDataAttr?: string
}

// The name and its editor share one box (height, padding and a 1px border), so opening the editor moves nothing.
const NAME_BOX = 'h-7 rounded-md border px-1.5 text-sm leading-6.5 font-semibold'

export function QuillSceneName({
    name: initialName,
    isLoading = false,
    onChange,
    canEdit = false,
    forceEdit = false,
    renameDebounceMs,
    saveOnBlur = false,
    onGenerateMetadata,
    isGeneratingMetadata = false,
    suffix,
    editDataAttr = 'scene-name-edit',
}: QuillSceneNameProps): JSX.Element {
    const { name, isEditing, containerRef, startEditing, change, blur, saveFromEnter, cancel } = useSceneNameEditing({
        name: initialName,
        isLoading,
        onChange,
        forceEdit,
        renameDebounceMs,
        saveOnBlur,
        isGeneratingMetadata,
    })
    const editable = !!onChange && canEdit
    const label = name || <span className="text-muted-foreground">Unnamed</span>

    if (isLoading) {
        // Same height as the name, so switching between resources does not shift the bar.
        return (
            <div className="flex h-7 min-w-0 flex-1 items-center">
                <SkeletonText lines={1} className="w-60 max-w-full" />
            </div>
        )
    }

    if (editable && isEditing) {
        return (
            <div ref={containerRef} className="flex min-w-0 flex-1 items-center gap-1" data-attr="scene-name-edit-row">
                <Input
                    aria-label="Name"
                    name="name"
                    value={name || ''}
                    readOnly={isGeneratingMetadata}
                    placeholder="Enter name"
                    onChange={(event: React.ChangeEvent<HTMLInputElement>) => change(event.target.value)}
                    onBlur={blur}
                    onKeyDown={(event: React.KeyboardEvent<HTMLInputElement>) => {
                        if (event.key === 'Enter') {
                            event.preventDefault()
                            saveFromEnter(event.currentTarget.value)
                            if (!forceEdit) {
                                event.currentTarget.blur()
                            }
                        } else if (event.key === 'Escape') {
                            event.preventDefault()
                            cancel()
                        }
                    }}
                    autoFocus={!forceEdit}
                    data-attr="scene-title-textarea"
                    className={cn(NAME_BOX, 'max-w-120 min-w-0 flex-1', isGeneratingMetadata && 'opacity-80')}
                />
                {onGenerateMetadata && (
                    <Tooltip>
                        <TooltipTrigger
                            render={
                                <Button
                                    variant="outline"
                                    size="icon-sm"
                                    aria-label="Generate name and description"
                                    disabled={isGeneratingMetadata}
                                    onClick={onGenerateMetadata}
                                />
                            }
                        >
                            <IconSparkles />
                        </TooltipTrigger>
                        <TooltipContent>
                            {isGeneratingMetadata ? 'Thinking...' : 'Generate name and description'}
                        </TooltipContent>
                    </Tooltip>
                )}
            </div>
        )
    }

    return (
        <div data-attr="scene-name" className="flex min-w-0 items-center gap-1">
            {editable ? (
                <h1 className="m-0 flex min-w-0">
                    <button
                        type="button"
                        onClick={startEditing}
                        disabled={isGeneratingMetadata}
                        title={isGeneratingMetadata ? 'Finish generating before editing' : 'Edit name'}
                        data-attr={editDataAttr}
                        className={cn(
                            NAME_BOX,
                            'min-w-0 cursor-text truncate border-transparent text-start text-foreground',
                            'hover:bg-fill-hover focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:outline-none disabled:cursor-not-allowed'
                        )}
                    >
                        {label}
                    </button>
                </h1>
            ) : (
                <h1 className={cn(NAME_BOX, 'm-0 min-w-0 truncate border-transparent text-foreground')}>{label}</h1>
            )}
            {suffix}
        </div>
    )
}

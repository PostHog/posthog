import { useActions, useValues } from 'kea'
import { useRef, useState } from 'react'

import { IconTrash } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { IconDragHandle } from 'lib/lemon-ui/icons'

import { TourStep, productToursLogic } from './productToursLogic'

interface DragState {
    dragIndex: number | null
    dropIndex: number | null
}

function StepRow({
    step,
    index,
    dragState,
    onDragStart,
    onDragEnter,
    onDragEnd,
    onEdit,
    onDelete,
}: {
    step: TourStep
    index: number
    dragState: DragState
    onDragStart: (index: number) => void
    onDragEnter: (index: number) => void
    onDragEnd: () => void
    onEdit: () => void
    onDelete: () => void
}): JSX.Element {
    const isDragging = dragState.dragIndex === index
    const isDropTarget = dragState.dropIndex === index && dragState.dragIndex !== index

    // Extract title from TipTap content
    const title = step.content?.content?.[0]?.content?.[0]?.text || 'Untitled step'
    const selectorPreview = step.selector.length > 25 ? step.selector.slice(0, 25) + '...' : step.selector

    return (
        <div
            draggable
            onDragStart={(e) => {
                e.dataTransfer.effectAllowed = 'move'
                onDragStart(index)
            }}
            onDragEnter={() => onDragEnter(index)}
            onDragOver={(e) => e.preventDefault()}
            onDragEnd={onDragEnd}
            onClick={onEdit}
            className={`
                group flex items-center gap-2 px-2 py-1.5 rounded-md cursor-pointer
                transition-all duration-200 ease-out
                ${isDragging ? 'opacity-40 scale-95' : 'opacity-100 scale-100'}
                ${isDropTarget ? 'translate-y-1 bg-primary/10 border-primary' : 'bg-bg-3000 hover:bg-border'}
                border border-transparent
            `}
        >
            <div className="cursor-grab active:cursor-grabbing text-muted hover:text-default transition-colors">
                <IconDragHandle className="w-4 h-4" />
            </div>

            <div className="flex items-center justify-center w-5 h-5 rounded-full bg-border text-xs font-medium">
                {index + 1}
            </div>

            <div className="flex-1 min-w-0">
                <div className="text-sm font-medium truncate">{title}</div>
                <div className="text-[10px] font-mono text-muted truncate">{selectorPreview}</div>
            </div>

            <LemonButton
                icon={<IconTrash />}
                size="xsmall"
                type="tertiary"
                status="danger"
                onClick={(e) => {
                    e.stopPropagation()
                    onDelete()
                }}
                className="opacity-0 group-hover:opacity-100 transition-opacity"
                tooltip="Delete step"
            />
        </div>
    )
}

export function StepList(): JSX.Element | null {
    const { tourForm } = useValues(productToursLogic)
    const { setTourFormValue, editStep, removeStep } = useActions(productToursLogic)
    const [dragState, setDragState] = useState<DragState>({ dragIndex: null, dropIndex: null })
    const listRef = useRef<HTMLDivElement>(null)

    const steps = tourForm?.steps ?? []

    if (steps.length === 0) {
        return null
    }

    const handleDragStart = (index: number): void => {
        setDragState({ dragIndex: index, dropIndex: null })
    }

    const handleDragEnter = (index: number): void => {
        if (dragState.dragIndex !== null && dragState.dragIndex !== index) {
            setDragState((prev) => ({ ...prev, dropIndex: index }))
        }
    }

    const handleDragEnd = (): void => {
        const { dragIndex, dropIndex } = dragState

        if (dragIndex !== null && dropIndex !== null && dragIndex !== dropIndex) {
            const newSteps = [...steps]
            const [moved] = newSteps.splice(dragIndex, 1)
            newSteps.splice(dropIndex, 0, moved)
            setTourFormValue('steps', newSteps)
        }

        setDragState({ dragIndex: null, dropIndex: null })
    }

    return (
        <div ref={listRef} className="space-y-1 max-h-48 overflow-y-auto pr-1" onDragOver={(e) => e.preventDefault()}>
            {steps.map((step, index) => (
                <StepRow
                    key={step.id}
                    step={step}
                    index={index}
                    dragState={dragState}
                    onDragStart={handleDragStart}
                    onDragEnter={handleDragEnter}
                    onDragEnd={handleDragEnd}
                    onEdit={() => editStep(index)}
                    onDelete={() => removeStep(index)}
                />
            ))}

            {/* Drop indicator at the end */}
            {dragState.dragIndex !== null && (
                <div
                    onDragEnter={() => setDragState((prev) => ({ ...prev, dropIndex: steps.length }))}
                    onDragOver={(e) => e.preventDefault()}
                    className={`
                        h-8 rounded-md border-2 border-dashed transition-colors
                        ${dragState.dropIndex === steps.length ? 'border-primary bg-primary/5' : 'border-border'}
                    `}
                />
            )}
        </div>
    )
}

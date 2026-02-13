import { useActions, useValues } from 'kea'

import { IconChevronDown, IconCursorClick, IconTrash, IconWarning } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSegmentedButton } from '@posthog/lemon-ui'

import { IconDragHandle } from 'lib/lemon-ui/icons'
import { getStepIcon, getStepTitle, hasElementTarget, hasIncompleteTargeting } from 'scenes/product-tours/stepUtils'

import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'
import { joinWithUiHost } from '~/toolbar/utils'

import { TourStep, productToursLogic } from './productToursLogic'

interface StepCardProps {
    step: TourStep
    index: number
    isExpanded: boolean
    onToggleExpand: () => void
    onDragStart: () => void
    onDragOver: (e: React.DragEvent) => void
    onDragEnd: () => void
    isDragging: boolean
    isDropTarget: boolean
}

export function StepCard({
    step,
    index,
    isExpanded,
    onToggleExpand,
    onDragStart,
    onDragOver,
    onDragEnd,
    isDragging,
    isDropTarget,
}: StepCardProps): JSX.Element {
    const { uiHost, temporaryToken } = useValues(toolbarConfigLogic)
    const { selectingStepIndex, expandedStepRect } = useValues(productToursLogic)
    const { removeStep, updateStep, setEditorState } = useActions(productToursLogic)

    const hasTarget = hasElementTarget(step)
    const isSelecting = selectingStepIndex === index
    const elementNotFound = hasTarget && isExpanded && selectingStepIndex === null && expandedStepRect === null
    const isMissingElement = hasIncompleteTargeting(step)

    const handleReselectElement = (): void => {
        setEditorState({ mode: 'selecting', stepIndex: index })
    }

    const truncatedSelector =
        step.selector && step.selector.length > 25 ? step.selector.slice(0, 22) + '...' : step.selector

    const screenshotUrl = step.screenshotMediaId
        ? joinWithUiHost(uiHost, `/uploaded_media/${step.screenshotMediaId}?token=${temporaryToken}`)
        : null

    return (
        <div
            className="rounded-lg overflow-hidden transition-all"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                opacity: isDragging ? 0.4 : 1,
                transform: isDragging ? 'scale(0.98)' : 'scale(1)',
                border: `1px solid ${
                    isDropTarget || isSelecting
                        ? 'var(--primary-3000)'
                        : isMissingElement
                          ? 'var(--danger)'
                          : 'var(--border-bold-3000)'
                }`,
                boxShadow:
                    isDropTarget || isSelecting
                        ? '0 0 0 2px var(--primary-3000)'
                        : isMissingElement
                          ? '0 0 0 2px var(--danger)'
                          : 'none',
                backgroundColor: isExpanded ? 'var(--secondary-3000)' : 'var(--color-bg-light)',
            }}
            onDragOver={onDragOver}
        >
            <button
                type="button"
                onClick={onToggleExpand}
                className="w-full flex items-center gap-2 p-2.5 text-left bg-transparent border-none cursor-pointer"
            >
                <span className="text-muted-3000 cursor-grab" draggable onDragStart={onDragStart} onDragEnd={onDragEnd}>
                    <IconDragHandle className="w-3 h-3" />
                </span>

                <span
                    className="w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-semibold flex-shrink-0"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{
                        backgroundColor: 'var(--primary-3000)',
                        color: '#fff',
                    }}
                >
                    {index + 1}
                </span>

                <div className="flex-1 min-w-0 flex flex-col gap-0.5">
                    <div className="flex items-center gap-1.5">
                        <span className="text-muted-3000">{getStepIcon(step.type)}</span>
                        <span className="text-[13px] font-medium overflow-hidden text-ellipsis whitespace-nowrap">
                            {getStepTitle(step, index)}
                        </span>
                    </div>
                    {isMissingElement && (
                        <span className="text-[10px] text-danger flex items-center gap-1">
                            <IconWarning className="w-3 h-3" />{' '}
                            {step.elementTargeting === 'manual' ? 'Enter a selector' : 'Select an element'}
                        </span>
                    )}
                    {hasTarget && step.elementTargeting === 'manual' && step.selector && !isExpanded && (
                        <span
                            title={step.selector}
                            className="text-[10px] font-mono text-muted-3000 overflow-hidden text-ellipsis whitespace-nowrap"
                        >
                            {truncatedSelector}
                        </span>
                    )}
                </div>

                {step.elementTargeting !== 'manual' && screenshotUrl && !isExpanded && (
                    <div className="w-8 h-6 rounded overflow-hidden border border-border-3000 flex-shrink-0 bg-secondary-3000">
                        <img
                            src={screenshotUrl}
                            alt=""
                            className="w-full h-full object-cover"
                            onError={(e) => {
                                e.currentTarget.style.display = 'none'
                            }}
                        />
                    </div>
                )}

                <IconChevronDown
                    className="w-4 h-4 text-muted-3000 transition-transform flex-shrink-0"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{
                        transform: isExpanded ? 'rotate(180deg)' : 'rotate(0deg)',
                    }}
                />
            </button>

            {isExpanded && (
                <div className="px-3 pb-3 pt-1 flex flex-col gap-3">
                    {step.elementTargeting !== 'manual' && screenshotUrl && (
                        <div className="rounded-md overflow-hidden border border-border-3000 bg-secondary-3000">
                            <img
                                src={screenshotUrl}
                                alt="Element preview"
                                className="w-full h-auto max-h-24 object-contain"
                                onError={(e) => {
                                    e.currentTarget.parentElement!.style.display = 'none'
                                }}
                            />
                        </div>
                    )}

                    {hasTarget ? (
                        <>
                            {elementNotFound && (
                                <div className="flex items-center gap-2 p-2 rounded-md text-xs bg-warning-highlight">
                                    <IconWarning /> Element not found on this page
                                </div>
                            )}

                            <div>
                                <label className="block text-[11px] font-medium text-muted-3000 mb-1.5">
                                    Targeting
                                </label>
                                <LemonSegmentedButton
                                    size="xsmall"
                                    fullWidth
                                    value={step.elementTargeting ?? 'auto'}
                                    onChange={(value) => updateStep(index, { elementTargeting: value })}
                                    options={[
                                        { value: 'auto', label: 'Auto' },
                                        { value: 'manual', label: 'Manual' },
                                    ]}
                                />
                            </div>

                            {step.elementTargeting === 'manual' && (
                                <div>
                                    <label className="block text-[11px] font-medium text-muted-3000 mb-1.5">
                                        CSS selector
                                    </label>
                                    <LemonInput
                                        size="small"
                                        value={step.selector || ''}
                                        onChange={(value) => updateStep(index, { selector: value, element: undefined })}
                                        placeholder="#my-element, .my-class"
                                        className="font-mono text-xs"
                                    />
                                </div>
                            )}

                            <div>
                                <label className="block text-[11px] font-medium text-muted-3000 mb-1.5">
                                    Advance on
                                </label>
                                <LemonSegmentedButton
                                    size="xsmall"
                                    fullWidth
                                    value={step.progressionTrigger || 'button'}
                                    onChange={(value) => updateStep(index, { progressionTrigger: value })}
                                    options={[
                                        { value: 'button', label: 'Next button' },
                                        { value: 'click', label: 'Element click' },
                                    ]}
                                />
                            </div>

                            <div className="flex gap-2">
                                <LemonButton
                                    size="small"
                                    type="secondary"
                                    fullWidth
                                    icon={<IconCursorClick />}
                                    onClick={handleReselectElement}
                                >
                                    Change
                                </LemonButton>
                                {step.type === 'modal' && (
                                    <LemonButton
                                        size="small"
                                        type="tertiary"
                                        status="danger"
                                        onClick={() =>
                                            updateStep(index, {
                                                type: 'modal',
                                                selector: undefined,
                                                inferenceData: undefined,
                                                screenshotMediaId: undefined,
                                                useManualSelector: undefined,
                                                element: undefined,
                                                elementTargeting: undefined,
                                            })
                                        }
                                        icon={<IconTrash />}
                                    />
                                )}
                            </div>
                        </>
                    ) : step.type === 'modal' ? (
                        <LemonButton
                            size="small"
                            type="secondary"
                            fullWidth
                            icon={<IconCursorClick />}
                            onClick={handleReselectElement}
                        >
                            Attach to element
                        </LemonButton>
                    ) : null}

                    <LemonButton
                        size="small"
                        type="tertiary"
                        status="danger"
                        fullWidth
                        icon={<IconTrash />}
                        onClick={() => removeStep(index)}
                    >
                        Delete step
                    </LemonButton>
                </div>
            )}
        </div>
    )
}

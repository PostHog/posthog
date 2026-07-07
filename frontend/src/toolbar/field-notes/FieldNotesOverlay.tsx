import { useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'
import { LemonButton, LemonTextArea } from '@posthog/lemon-ui'

import { ElementHighlight } from '~/toolbar/product-tours/ElementHighlight'

import { fieldNotesLogic } from './fieldNotesLogic'

const COMMENT_BOX_WIDTH = 320

// Always-mounted overlay: draws the hover/selected highlights, the "click an element"
// banner during selection, and the comment box anchored to the selected element. Living
// here (not in the toolbar menu popup) decouples it from the menu's open/close/blur
// lifecycle, so selecting an element reliably opens the write box.
export function FieldNotesOverlay(): JSX.Element | null {
    const { isFieldNoting, hoverElementRect, selectedElementRect, selectedElement, comment, submitResultLoading } =
        useValues(fieldNotesLogic)
    const { stopFieldNote, setComment, submitFieldNote, clearSelection } = useActions(fieldNotesLogic)

    if (!isFieldNoting && !selectedElement) {
        return null
    }

    // Anchor the comment box just below the element, clamped into the viewport.
    let boxTop = 80
    let boxLeft = 16
    if (selectedElementRect) {
        boxTop = Math.max(
            8,
            Math.min(selectedElementRect.top + selectedElementRect.height + 8, window.innerHeight - 240)
        )
        boxLeft = Math.min(Math.max(selectedElementRect.left, 8), window.innerWidth - COMMENT_BOX_WIDTH - 8)
    }

    return (
        <>
            {selectedElementRect && <ElementHighlight rect={selectedElementRect} isSelected />}
            {isFieldNoting && hoverElementRect && <ElementHighlight rect={hoverElementRect} />}

            {isFieldNoting && !selectedElement && (
                <div
                    className="fixed flex items-center gap-3 text-white text-sm font-medium"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{
                        left: '50%',
                        transform: 'translateX(-50%)',
                        top: 16,
                        paddingLeft: 16,
                        paddingRight: 8,
                        paddingTop: 10,
                        paddingBottom: 10,
                        borderRadius: 999,
                        backgroundColor: 'var(--primary-3000)',
                        boxShadow: '0 4px 12px rgba(29, 74, 255, 0.3)',
                        zIndex: 2147483020,
                        pointerEvents: 'auto',
                    }}
                >
                    <span>Click an element to add a note</span>
                    <button
                        type="button"
                        onClick={() => stopFieldNote()}
                        className="p-1.5 rounded-full border-none cursor-pointer flex items-center justify-center"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ background: 'rgba(255, 255, 255, 0.2)', color: '#fff' }}
                    >
                        <IconX className="w-4 h-4" />
                    </button>
                </div>
            )}

            {selectedElement && (
                <div
                    className="fixed flex flex-col gap-2 p-3 rounded shadow-xl"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{
                        top: boxTop,
                        left: boxLeft,
                        width: COMMENT_BOX_WIDTH,
                        backgroundColor: 'var(--color-bg-3000, #1d1f27)',
                        color: 'var(--text-3000, #fff)',
                        border: '1px solid var(--border-bold-3000, #3f4150)',
                        zIndex: 2147483021,
                        pointerEvents: 'auto',
                    }}
                    onClick={(e) => e.stopPropagation()}
                >
                    <div className="text-xs font-semibold uppercase opacity-70">New field note</div>
                    <LemonTextArea
                        placeholder="What should change about this element? (⌘↵ to save)"
                        value={comment}
                        onChange={setComment}
                        onPressCmdEnter={() => comment.trim() && !submitResultLoading && submitFieldNote()}
                        minRows={3}
                        autoFocus
                    />
                    <div className="flex gap-2">
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={() => clearSelection()}
                            className="flex-1"
                            center
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            size="small"
                            onClick={() => submitFieldNote()}
                            loading={submitResultLoading}
                            disabledReason={!comment.trim() ? 'Write a comment first' : undefined}
                            className="flex-1"
                            center
                        >
                            Save
                        </LemonButton>
                    </div>
                </div>
            )}
        </>
    )
}

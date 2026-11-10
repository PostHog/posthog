import { useEffect, useRef } from 'react'

import { IconDatabase } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { SaveToDatasetButton, SaveToDatasetButtonProps } from '../../../datasets/SaveToDatasetButton'
import { saveToDatasetButtonLogic } from '../../../datasets/saveToDatasetButtonLogic'
import type { RawLoad } from '../types'

export interface DatasetButtonSlotProps {
    raw: RawLoad | undefined
    source: SaveToDatasetButtonProps | null
    onLoad: () => void
}

type Intent = 'none' | 'focus' | 'open'

const REAL_BUTTON_SELECTOR = '[data-attr="save-to-dataset-open"]'
const RETRY_TEXT = "Couldn't load this step's event. Click to try again."

// The button needs the step's raw event, which is read when the user reaches for it. The real button is a different
// DOM element from the placeholder, so the swap drops keyboard focus and the click that started the read. The slot
// remembers that intent and gives focus to the real button, and opens its dropdown for a press.
export function DatasetButtonSlot({ raw, source, onLoad }: DatasetButtonSlotProps): JSX.Element | null {
    const slotRef = useRef<HTMLSpanElement>(null)
    const intent = useRef<Intent>('none')
    const ready = source !== null
    const disabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.LlmAnalytics,
        AccessControlLevel.Editor
    )

    useEffect(() => {
        if (ready) {
            return
        }
        // A press anywhere else means the user moved on. Blur cannot tell this apart from the swap, because a press on
        // text that cannot take focus also moves focus to nothing.
        const cancelOnPressElsewhere = (event: PointerEvent): void => {
            if (!(event.target instanceof Node && slotRef.current?.contains(event.target))) {
                intent.current = 'none'
            }
        }
        document.addEventListener('pointerdown', cancelOnPressElsewhere, true)
        return () => document.removeEventListener('pointerdown', cancelOnPressElsewhere, true)
    }, [ready])

    useEffect(() => {
        if (!ready || intent.current === 'none') {
            return
        }
        const focusWasLost = document.activeElement === null || document.activeElement === document.body
        if (focusWasLost) {
            slotRef.current?.querySelector<HTMLElement>(REAL_BUTTON_SELECTOR)?.focus()
        }
        if (intent.current === 'open') {
            saveToDatasetButtonLogic.findMounted()?.actions.setDropdownVisible(true)
        }
        intent.current = 'none'
    }, [ready])

    if (source) {
        return (
            <span className="inline-flex" ref={slotRef}>
                <SaveToDatasetButton {...source} />
            </span>
        )
    }
    if (raw?.status === 'ready' || (raw?.status === 'error' && raw.failure === 'not_found')) {
        return null
    }
    const loading = raw?.status === 'loading'
    const failed = raw?.status === 'error'
    return (
        <span
            className="inline-flex"
            ref={slotRef}
            onMouseEnter={onLoad}
            onFocusCapture={() => {
                intent.current = intent.current === 'none' ? 'focus' : intent.current
                onLoad()
            }}
            onBlurCapture={(event) => {
                if (event.relatedTarget !== null) {
                    intent.current = 'none'
                }
            }}
        >
            <LemonButton
                type="secondary"
                size="xsmall"
                icon={loading ? <Spinner /> : <IconDatabase />}
                aria-busy={loading}
                disabledReason={disabledReason}
                tooltip={failed ? RETRY_TEXT : undefined}
                aria-label={failed ? `Add to dataset. ${RETRY_TEXT}` : undefined}
                // The read can finish while the button is held down. The swap then removes the pressed element, so
                // its click never fires, and the press itself has to record the intent.
                onMouseDown={(event) => {
                    if (event.button === 0 && !disabledReason) {
                        intent.current = 'open'
                    }
                }}
                onClick={() => {
                    intent.current = 'open'
                    onLoad()
                }}
                data-attr="save-to-dataset-placeholder"
            >
                Add to dataset
            </LemonButton>
        </span>
    )
}

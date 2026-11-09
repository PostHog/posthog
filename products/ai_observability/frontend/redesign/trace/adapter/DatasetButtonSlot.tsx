import { useEffect, useRef } from 'react'

import { IconDatabase } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'

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
// remembers that intent and gives focus to the real button, and opens its dropdown for a click.
export function DatasetButtonSlot({ raw, source, onLoad }: DatasetButtonSlotProps): JSX.Element | null {
    const slotRef = useRef<HTMLSpanElement>(null)
    const intent = useRef<Intent>('none')
    const ready = source !== null

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
            <AccessControlAction
                resourceType={AccessControlResourceType.LlmAnalytics}
                minAccessLevel={AccessControlLevel.Editor}
            >
                <LemonButton
                    type="secondary"
                    size="xsmall"
                    icon={loading ? <Spinner /> : <IconDatabase />}
                    aria-busy={loading}
                    tooltip={failed ? RETRY_TEXT : undefined}
                    aria-label={failed ? `Add to dataset. ${RETRY_TEXT}` : undefined}
                    onClick={() => {
                        intent.current = 'open'
                        onLoad()
                    }}
                    data-attr="save-to-dataset-placeholder"
                >
                    Add to dataset
                </LemonButton>
            </AccessControlAction>
        </span>
    )
}

import type { OpenPersonsModalProps } from 'scenes/trends/persons-modal/PersonsModal'

import type { DataTableNode } from '~/queries/schema/schema-general'

export interface CapturedPersonsModal extends OpenPersonsModalProps {
    open?: () => void
    rowsQuery?: DataTableNode
}

type Capture = (props: CapturedPersonsModal) => void
let clickCapture: Capture | null = null
let releaseTimer: ReturnType<typeof setTimeout> | undefined

// Keep the chart's existing actor-query builder. Only defer modal requests made during this click;
// the timeout spans both React capture and native chart listeners, which run in separate microtasks.
export function capturePersonsModalForClick(capture: Capture): void {
    clickCapture = capture
    clearTimeout(releaseTimer)
    releaseTimer = setTimeout(() => {
        if (clickCapture === capture) {
            clickCapture = null
        }
    }, 0)
}

export function consumePersonsModalClick(props: CapturedPersonsModal): boolean {
    const capture = clickCapture
    if (!capture) {
        return false
    }
    clickCapture = null
    clearTimeout(releaseTimer)
    capture(props)
    return true
}

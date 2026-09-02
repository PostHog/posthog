import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { ToastButton } from 'lib/lemon-ui/LemonToast/LemonToast'
import { PromiseTimeoutError, withTimeout } from 'lib/utils/async'
import { uuid } from 'lib/utils/dom'

import { ExportedAssetType } from '~/types'

import {
    ExportNudgeCandidate,
    captureExportNudgeCheckFailed,
    exportNudgeEventProperties,
    lookUpExportNudge,
    resolveExportNudgeEligibility,
} from 'products/subscriptions/frontend/components/Subscriptions/exportNudge/exportNudgeLogic'
import {
    ExportNudgeSubject,
    exportNudgeSubjectFor,
} from 'products/subscriptions/frontend/components/Subscriptions/exportNudge/exportNudgeSubject'
import {
    ExportNudgeMessage,
    claimExportNudgeMessage,
} from 'products/subscriptions/frontend/components/Subscriptions/exportNudge/ExportNudgeToast'

import { TriggerExportProps } from './exporter'

const EXPORT_COMPLETE_MESSAGE = 'Export complete!'
// The check normally answers long before the export lands.
const NUDGE_RESOLUTION_TIMEOUT_MS = 5000

/** An export's offer: known up front, or still resolving while the export runs. */
export interface ExportNudge {
    message: ExportNudgeMessage | null
    resolving: Promise<ExportNudgeCandidate | null>
}

const NO_NUDGE: ExportNudge = { message: null, resolving: Promise.resolve(null) }

/** What an export that acknowledged its kickoff hands to the toast it finishes on. */
export interface KickoffToast {
    toastId: string
    nudge: ExportNudge
}

/**
 * Both scenes load the subject's subscriptions to show the subscribe button's count, so most exports
 * answer eligibility on the spot and put the offer in the toast's first frame. The rest start the
 * check here and fold it in when the export settles.
 */
export const startExportNudge = (exportData: TriggerExportProps | ExportedAssetType): ExportNudge => {
    const subject = exportNudgeSubjectFor(exportData)
    if (!subject) {
        return NO_NUDGE
    }
    const lookup = lookUpExportNudge(subject)
    if (lookup.status === 'ineligible') {
        return NO_NUDGE
    }
    if (lookup.status === 'eligible') {
        return { message: claimExportNudgeMessage(lookup.candidate), resolving: Promise.resolve(null) }
    }
    return { message: null, resolving: resolveNudgeWhileExporting(subject) }
}

// A stalled or failed check must never hold up the export's own feedback.
const resolveNudgeWhileExporting = async (subject: ExportNudgeSubject): Promise<ExportNudgeCandidate | null> =>
    await withTimeout(resolveExportNudgeEligibility(subject), NUDGE_RESOLUTION_TIMEOUT_MS).catch((error) => {
        if (error instanceof PromiseTimeoutError) {
            // Every other failure reports its own step. Without this one, a stalled check looks the
            // same as an exporter who was ineligible.
            captureExportNudgeCheckFailed('timeout', exportNudgeEventProperties(subject))
        }
        return null
    })

// A toast waits to be clicked, rather than closing on a timer, while it carries both an unanswered
// offer and a file the user has not taken yet.
const holdOpenFor = (message: ExportNudgeMessage | null, action?: ToastButton): { autoClose?: false } =>
    message && action ? { autoClose: false } : {}

interface ToastFrame {
    message: string | JSX.Element
    /** Empty where the offer lays the action out beside its own CTA, so it is not rendered twice. */
    button?: ToastButton
}

const toastFrame = (
    message: ExportNudgeMessage | null,
    headline: string,
    toastId: number | string,
    action?: ToastButton
): ToastFrame => (message ? { message: message(headline, toastId, action) } : { message: headline, button: action })

export const nudgeToastOptions = (
    nudge: ExportNudge,
    headline: string,
    toastId: number | string,
    action?: ToastButton
): { message: string | JSX.Element; button?: ToastButton; autoClose?: false } => {
    const frame = toastFrame(nudge.message, headline, toastId, action)
    return { ...frame, ...holdOpenFor(nudge.message, action) }
}

/**
 * Claiming happens here rather than when the check answers, because it reports an exposure: an
 * export that never renders the offer must not spend it.
 */
export const foldNudgeIntoSettledToast = async (
    nudge: ExportNudge,
    toastId: string,
    headline: string,
    action?: ToastButton
): Promise<void> => {
    const candidate = await nudge.resolving
    if (!candidate) {
        return
    }
    if (!lemonToast.isActive(toastId)) {
        captureExportNudgeCheckFailed('toast-gone', exportNudgeEventProperties(candidate.subject))
        return
    }
    const message = claimExportNudgeMessage(candidate)
    if (!message) {
        return
    }
    lemonToast.updateToSuccess(toastId, message(headline, toastId, action), { ...holdOpenFor(message, action) })
}

/**
 * Settles a finished export onto a toast carrying its Download button: the one it is already on if
 * that is still up, a fresh one otherwise. Updating a dismissed toast does nothing, which would
 * leave someone who closed the spinner with a file and nowhere to claim it from.
 */
export const settleWithDownload = async (
    nudge: ExportNudge,
    existingToastId: string | null,
    onDownload: () => void
): Promise<void> => {
    const reuse = !!existingToastId && lemonToast.isActive(existingToastId)
    const toastId = reuse && existingToastId ? existingToastId : 'export-complete-' + uuid()
    const downloadButton = { label: 'Download', action: onDownload }
    const { message, ...options } = nudgeToastOptions(nudge, EXPORT_COMPLETE_MESSAGE, toastId, downloadButton)

    if (reuse) {
        lemonToast.updateToSuccess(toastId, message, options)
    } else {
        lemonToast.success(message, { toastId, ...options })
    }
    await foldNudgeIntoSettledToast(nudge, toastId, EXPORT_COMPLETE_MESSAGE, downloadButton)
}

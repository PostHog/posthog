import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'

import { DISMISSAL_REASON_OPTIONS, DismissalReasonValue } from '../../utils/dismissalReasons'

export interface DismissReportDialogResult {
    reason: DismissalReasonValue
    note: string
}

interface OpenDismissReportDialogParams {
    /** Report title for single-report copy. Ignored when `selectedCount > 1`. */
    reportTitle?: string | null
    /** When greater than 1, copy reflects a bulk dismiss of the current selection. */
    selectedCount?: number
    /** Called with the chosen reason + note once the user confirms. */
    onConfirm: (result: DismissReportDialogResult) => void | Promise<void>
}

const REASON_SELECT_OPTIONS = DISMISSAL_REASON_OPTIONS.map((option) => ({
    value: option.value,
    label: option.label,
}))

/**
 * Opens the dismiss dialog. Mirrors desktop `DismissReportDialog`: pick a reason
 * (canonical {@link DISMISSAL_REASON_OPTIONS}) plus an optional note, then suppress.
 * The caller wires `onConfirm` to the bulk-dismiss action or a direct
 * `api.signalReports.setState(id, { state: 'suppressed', dismissal_reason, dismissal_note })`.
 */
export function openDismissReportDialog({
    reportTitle,
    selectedCount = 1,
    onConfirm,
}: OpenDismissReportDialogParams): void {
    const isBulk = selectedCount > 1
    const title = isBulk
        ? `Dismiss ${selectedCount} reports?`
        : `Dismiss report "${reportTitle?.trim() ? reportTitle : 'Untitled report'}"?`
    const description = isBulk
        ? 'These reports will be removed from your inbox. Your feedback is saved on each report and helps the agent.'
        : 'This report will be removed from your inbox. Your feedback is saved on the report and helps the agent.'

    LemonDialog.openForm({
        title,
        description,
        initialValues: { reason: null as DismissalReasonValue | null, note: '' },
        content: (
            <div className="flex flex-col gap-3 mt-2">
                <LemonField name="reason" label="Reason">
                    <LemonSelect options={REASON_SELECT_OPTIONS} placeholder="Pick a reason" />
                </LemonField>
                <LemonField name="note" label="Note" info="Optional — helps the agent learn">
                    <LemonTextArea placeholder="Optional: add detail" maxLength={4000} rows={3} />
                </LemonField>
            </div>
        ),
        errors: {
            reason: (reason) => (!reason ? "You haven't picked a reason" : undefined),
        },
        primaryButtonProps: { children: 'Dismiss & teach the agent' },
        shouldAwaitSubmit: true,
        onSubmit: async ({ reason, note }) => {
            if (!reason) {
                return
            }
            await onConfirm({ reason, note: (note ?? '').trim() })
        },
    })
}

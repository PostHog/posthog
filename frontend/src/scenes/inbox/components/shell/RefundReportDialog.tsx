import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonRadio, LemonRadioOption } from 'lib/lemon-ui/LemonRadio'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'

import { SignalReportRefundReasonEnumApi } from 'products/signals/frontend/generated/api.schemas'

export interface RefundReportDialogResult {
    reason: SignalReportRefundReasonEnumApi
    note: string
}

interface OpenRefundReportDialogParams {
    /** Report title for the dialog copy. */
    reportTitle?: string | null
    /** Called with the chosen reason + note once the user confirms. */
    onConfirm: (result: RefundReportDialogResult) => void | Promise<void>
}

// Values are the backend `SignalReportRefund.Reason` choices (via the generated enum); the future
// refund judge consumes them, so the labels spell out what each code means.
const REFUND_REASON_OPTIONS: LemonRadioOption<SignalReportRefundReasonEnumApi>[] = [
    { value: SignalReportRefundReasonEnumApi.PrIncorrect, label: "The PR doesn't fix what the report describes" },
    { value: SignalReportRefundReasonEnumApi.PrNotUseful, label: 'The PR works but is not useful to me' },
    { value: SignalReportRefundReasonEnumApi.Duplicate, label: 'Duplicate of work already covered' },
    { value: SignalReportRefundReasonEnumApi.Other, label: 'Something else…' },
]

/**
 * Opens the refund dialog (mirrors {@link openDismissReportDialog}): pick a required reason plus an
 * optional note, then refund. The caller wires `onConfirm` to the refund API call; refunding also
 * archives the report, so the copy says both. `shouldAwaitSubmit` keeps the primary button in a
 * loading state while the request is in flight, so it can't be double-submitted.
 */
export function openRefundReportDialog({ reportTitle, onConfirm }: OpenRefundReportDialogParams): void {
    LemonDialog.openForm({
        title: `Refund the PR for "${reportTitle?.trim() ? reportTitle : 'Untitled report'}"?`,
        description:
            "You won't pay for this PR and it won't count toward your included PRs. The report is archived as part of the refund and can't be restored.",
        maxWidth: '30rem',
        initialValues: { reason: null as SignalReportRefundReasonEnumApi | null, note: '' },
        content: (
            <div className="flex flex-col gap-3">
                <LemonField name="reason" label="Reason">
                    {({ value, onChange }) => (
                        <LemonRadio value={value} onChange={onChange} options={REFUND_REASON_OPTIONS} />
                    )}
                </LemonField>
                <LemonField name="note" label="Note" info="Optional – helps us review refunds">
                    <LemonTextArea placeholder="Optional: add detail" maxLength={4000} rows={3} />
                </LemonField>
            </div>
        ),
        errors: {
            reason: (reason) => (!reason ? "You haven't picked a reason" : undefined),
        },
        primaryButtonProps: { children: 'Refund' },
        shouldAwaitSubmit: true,
        onSubmit: async ({ reason, note }) => {
            if (!reason) {
                return
            }
            await onConfirm({ reason, note: (note ?? '').trim() })
        },
    })
}

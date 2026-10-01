import { LemonCheckbox } from '@posthog/lemon-ui'

import type { ReplayVisionScannerOptionProps } from './ReplayVisionScannerCard'

export function ReplayVisionScannerCheckbox({
    checked,
    onChange,
    disabledReason,
    sessionPrice,
}: ReplayVisionScannerOptionProps): JSX.Element {
    return (
        <LemonCheckbox
            bordered
            fullWidth
            checked={checked}
            onChange={onChange}
            disabledReason={disabledReason}
            data-attr="experiment-create-replay-vision-scanner"
            label={
                <div className="py-3">
                    <div className="font-semibold">Watch participant behavior with Replay Vision</div>
                    <div className="mt-1 font-normal text-sm text-muted">
                        Set up a scanner that classifies what participants do after experiment exposure. It is created
                        turned off, so nothing is scanned and no credits are used until you turn it on. You can adjust
                        its prompt, filters, and sampling first. A scanner keeps running after the experiment ends, so
                        turn it off when you are done.
                    </div>
                    <div className="font-normal text-sm text-muted mt-1">
                        Each scanned session costs {sessionPrice}. The scanner shows a projected monthly cost once the
                        experiment has participants.
                    </div>
                </div>
            }
        />
    )
}

import { IconSparkles } from '@posthog/icons'
import { LemonCheckbox } from '@posthog/lemon-ui'

import type { ReplayVisionScannerOptionProps } from './ReplayVisionScannerCard'

export function ReplayVisionScannerCheckbox({
    checked,
    onChange,
    disabledReason,
    sessionPrice,
    experimentScanners,
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
                    <div className="flex items-center gap-2 font-semibold">
                        {experimentScanners ? (
                            <>
                                <IconSparkles className="text-ai" />
                                Compare what users do in each variant
                            </>
                        ) : (
                            'Watch participant behavior with Replay Vision'
                        )}
                    </div>
                    <div className="mt-1 font-normal text-sm text-muted">
                        {experimentScanners
                            ? 'Set up an experiment scanner. It uses Replay vision to summarize the recordings of exposed users and shows each variant side by side. It turns on when you launch the experiment and stops when the experiment ends. Until launch, nothing is scanned and no credits are used.'
                            : 'Set up a scanner that classifies what participants do after experiment exposure. It is created turned off, so nothing is scanned and no credits are used until you turn it on. You can adjust its prompt, filters, and sampling first. A scanner keeps running after the experiment ends, so turn it off when you are done.'}
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

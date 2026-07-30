import { IconCheck } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

/** The billing step's short-circuit for a team that already subscribed: confirm and move on. */
export function SubscribedState({ onContinue }: { onContinue: () => void }): JSX.Element {
    return (
        <div className="flex flex-col gap-3">
            <div className="flex items-start gap-3 p-4 border border-success rounded-lg bg-success-highlight">
                <IconCheck className="size-5 text-success shrink-0 mt-0.5" />
                <div className="flex-1 min-w-0">
                    <p className="m-0 text-sm font-semibold">You're on pay-as-you-go</p>
                    <p className="m-0 text-xs text-muted">
                        Agents keep watching and reporting for free. You only pay when one ships a PR.
                    </p>
                </div>
            </div>
            <p className="text-xs text-muted m-0">Change or cancel any time from billing settings.</p>
            <LemonButton type="primary" status="alt" onClick={onContinue} className="self-end">
                Go to your inbox
            </LemonButton>
        </div>
    )
}

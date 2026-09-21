import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

/** The billing step's short-circuit for a team that already subscribed: confirm and move on. */
export function SubscribedState({
    onContinue,
    completing,
}: {
    onContinue: () => void
    completing: boolean
}): JSX.Element {
    return (
        <div className="flex flex-col gap-3">
            <LemonBanner type="success">
                <p className="m-0 text-sm font-semibold">You're on pay-as-you-go</p>
                <p className="m-0 text-xs font-normal">
                    Agents keep watching and reporting for free. You only pay when one ships a PR.
                </p>
            </LemonBanner>
            <p className="text-xs text-muted m-0">Change or cancel any time from billing settings.</p>
            <LemonButton type="primary" status="alt" onClick={onContinue} loading={completing} className="self-end">
                Go to the Inbox
            </LemonButton>
        </div>
    )
}

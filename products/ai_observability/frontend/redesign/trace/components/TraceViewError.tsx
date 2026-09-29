import { IconArrowLeft } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

export interface TraceViewErrorProps {
    message: string
    backHref: string
}

export function TraceViewError({ message, backHref }: TraceViewErrorProps): JSX.Element {
    return (
        <div className="flex flex-col items-start gap-2 py-8">
            <h2 className="m-0 text-lg font-semibold">We couldn't load this trace</h2>
            <p className="m-0 text-secondary">{message}</p>
            <LemonButton type="secondary" icon={<IconArrowLeft />} to={backHref}>
                Back to traces
            </LemonButton>
        </div>
    )
}

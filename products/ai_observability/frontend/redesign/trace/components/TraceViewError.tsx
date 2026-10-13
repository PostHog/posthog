import { IconArrowLeft } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LabeledLink } from '../types'

export interface TraceViewErrorProps {
    message: string
    backLink: LabeledLink
}

export function TraceViewError({ message, backLink }: TraceViewErrorProps): JSX.Element {
    return (
        <div className="flex flex-col items-start gap-2 py-8">
            <h2 className="m-0 text-lg font-semibold">We couldn't load this trace</h2>
            <p className="m-0 text-secondary">{message}</p>
            <LemonButton type="secondary" icon={<IconArrowLeft />} to={backLink.href}>
                {backLink.label}
            </LemonButton>
        </div>
    )
}

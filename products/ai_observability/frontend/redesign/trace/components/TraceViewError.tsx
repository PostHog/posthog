import { IconArrowLeft } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LabeledLink, LoadFailure } from '../types'

const MESSAGES: Record<LoadFailure, string> = {
    failed: 'Something went wrong while loading it. Try again in a moment.',
    not_found: 'It may have been deleted, or it is outside the retention period.',
}

export interface TraceViewErrorProps {
    loadFailure: LoadFailure
    backLink: LabeledLink | null
}

export function TraceViewError({ loadFailure, backLink }: TraceViewErrorProps): JSX.Element {
    return (
        <div className="flex flex-col items-start gap-2 py-8">
            <h2 className="m-0 text-lg font-semibold">We couldn't load this trace</h2>
            <p className="m-0 text-secondary">{MESSAGES[loadFailure]}</p>
            {backLink ? (
                <LemonButton type="secondary" icon={<IconArrowLeft />} to={backLink.href}>
                    {backLink.label}
                </LemonButton>
            ) : null}
        </div>
    )
}

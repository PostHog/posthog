import { lemonToast } from '@posthog/lemon-ui'
import api from 'lib/api'
import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import { useState } from 'react'

export type ExplainCSPViolationButtonProps = LemonButtonProps & {
    properties: Record<string, any>
    label: string
}

export const ExplainCSPViolationButton = ({
    properties,
    label,
    ...buttonProps
}: ExplainCSPViolationButtonProps): JSX.Element => {
    const [loading, setLoading] = useState(false)

    const handleClick = async (): Promise<void> => {
        setLoading(true)
        try {
            const r = await api.cspReporting.explain(properties)
            if (r) {
                lemonToast.success(r.response)
            } else {
                lemonToast.error('Failed to get CSP violation report explanation.')
            }
        } finally {
            setLoading(false)
        }
    }

    return (
        <LemonButton
            {...buttonProps}
            loading={loading}
            /* eslint-disable-next-line @typescript-eslint/no-misused-promises */
            onClick={handleClick}
        >
            {label}
        </LemonButton>
    )
}

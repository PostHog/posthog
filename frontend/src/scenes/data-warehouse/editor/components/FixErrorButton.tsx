import { IconSparkles, IconWarning } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'

import { FixErrorButtonSource, useFixErrorButtonState } from './useFixErrorButtonState'

interface FixErrorButtonProps {
    type: LemonButtonProps['type']
    size?: LemonButtonProps['size']
    contentOverride?: string
    source: FixErrorButtonSource
}

export function FixErrorButton({ type, size, contentOverride, source }: FixErrorButtonProps): JSX.Element {
    const { loading, failed, disabledReason, label, fix } = useFixErrorButtonState(source, contentOverride)

    return (
        <LemonButton
            type={type}
            size={size}
            disabledReason={disabledReason}
            loading={loading}
            icon={loading ? <Spinner /> : failed ? <IconWarning className="text-warning" /> : <IconSparkles />}
            onClick={fix}
        >
            {label}
        </LemonButton>
    )
}

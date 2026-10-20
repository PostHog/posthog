import { forwardRef } from 'react'

import { IconGear } from '@posthog/icons'

import { LemonButton } from '~/lib/lemon-ui/LemonButton'

export const LemonBreakdownOptionsButton = forwardRef<HTMLButtonElement, { onClick: () => void }>(
    function LemonBreakdownOptionsButton({ onClick }, ref): JSX.Element {
        return <LemonButton ref={ref} icon={<IconGear />} size="small" noPadding onClick={onClick} />
    }
)

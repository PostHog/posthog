import { forwardRef } from 'react'

import { BaseIcon } from '@posthog/icons'
import { IconComponent, IconProps } from '@posthog/icons/dist/src/types/icon-types'

export const IconDirectedGraph: IconComponent<IconProps> = forwardRef(
    function IconDirectedGraph(props, ref): JSX.Element {
        return (
            <BaseIcon ref={ref} {...props}>
                <circle cx="12" cy="6" r="2.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
                <circle cx="6" cy="18" r="2.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
                <circle cx="18" cy="18" r="2.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
                <path d="M 11 9 L 7 15" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                <path d="M 13 9 L 17 15" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </BaseIcon>
        )
    }
)

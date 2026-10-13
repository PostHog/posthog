import { ReactNode } from 'react'

import { LemonTag } from '@posthog/lemon-ui'

export function DataQualityTabLabel({ children }: { children?: ReactNode }): JSX.Element {
    return (
        <span className="flex items-center gap-1">
            Data quality
            <LemonTag type="completion">Beta</LemonTag>
            {children}
        </span>
    )
}

import { LemonDivider } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

export interface SceneDividerProps {
    className?: string
}

export function SceneDivider({ className }: SceneDividerProps): JSX.Element {
    return <LemonDivider className={cn('scene-divider -mx-4 w-[calc(100%+var(--spacing)*8)]', className)} />
}

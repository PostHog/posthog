import type { ReactNode } from 'react'

import { MenuLabel, cn } from '@posthog/quill'

export function TodayPaneGroupLabel({ children, first }: { children: ReactNode; first: boolean }): JSX.Element {
    return <MenuLabel className={cn('pt-1 pb-0.5', !first && 'mt-2')}>{children}</MenuLabel>
}

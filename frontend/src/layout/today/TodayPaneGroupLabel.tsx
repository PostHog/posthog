import type { ReactNode } from 'react'

import { Text, cn } from '@posthog/quill'

export function TodayPaneGroupLabel({ children, first }: { children: ReactNode; first: boolean }): JSX.Element {
    return (
        <Text size="xs" weight="medium" variant="muted" className={cn('block px-2 pb-1', first ? 'pt-1' : 'pt-3')}>
            {children}
        </Text>
    )
}

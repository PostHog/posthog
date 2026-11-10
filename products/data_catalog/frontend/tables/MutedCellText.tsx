import { ReactNode } from 'react'

import { Text } from '@posthog/quill'

export function MutedCellText({ children }: { children: ReactNode }): JSX.Element {
    return (
        <Text size="xs" variant="muted" className="whitespace-nowrap">
            {children}
        </Text>
    )
}

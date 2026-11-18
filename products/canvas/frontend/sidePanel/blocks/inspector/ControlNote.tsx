import { ReactNode } from 'react'

import { Text } from '@posthog/quill'

/** An explanation in place of settings, for blocks and elements the inspector cannot change. */
export function ControlNote({ children }: { children: ReactNode }): JSX.Element {
    return (
        <Text size="xs" variant="muted">
            {children}
        </Text>
    )
}

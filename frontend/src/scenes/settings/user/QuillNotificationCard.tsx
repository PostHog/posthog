import { ReactNode } from 'react'

import { Card, CardContent } from '@posthog/quill'

export function QuillNotificationCard({ children }: { children: ReactNode }): JSX.Element {
    return (
        <Card size="sm">
            <CardContent className="flex flex-col gap-3">{children}</CardContent>
        </Card>
    )
}

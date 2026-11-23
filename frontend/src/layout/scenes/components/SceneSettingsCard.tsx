import { ReactNode } from 'react'

import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@posthog/quill'

export interface SceneSettingsCardProps {
    title: ReactNode
    description?: ReactNode
    action?: ReactNode
    children: ReactNode
    dataAttr?: string
}

/**
 * One group of an object's settings, under the Today layout. Each child row puts its label on the left and its
 * control on the right, so an object page reads like a settings page.
 */
export function SceneSettingsCard({
    title,
    description,
    action,
    children,
    dataAttr,
}: SceneSettingsCardProps): JSX.Element {
    return (
        <Card flush data-attr={dataAttr}>
            <CardHeader>
                <CardTitle role="heading" aria-level={2}>
                    {title}
                </CardTitle>
                {description && <CardDescription>{description}</CardDescription>}
                {action && <CardAction>{action}</CardAction>}
            </CardHeader>
            <CardContent className="@container/settings-card flex flex-col divide-y divide-border">
                {children}
            </CardContent>
        </Card>
    )
}

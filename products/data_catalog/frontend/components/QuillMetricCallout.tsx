import type { ReactNode } from 'react'

import { Item, ItemActions, ItemContent, Text } from '@posthog/quill'

export interface QuillMetricCalloutProps {
    tone: 'info' | 'warning' | 'destructive'
    children: ReactNode
    actions?: ReactNode
}

export function QuillMetricCallout({ tone, children, actions }: QuillMetricCalloutProps): JSX.Element {
    return (
        <Item variant="outline" size="sm" tone={tone} className="flex-wrap">
            <ItemContent className="min-w-0">
                <Text size="xs" render={<div />} className="m-0">
                    {children}
                </Text>
            </ItemContent>
            {actions && <ItemActions className="flex-wrap">{actions}</ItemActions>}
        </Item>
    )
}

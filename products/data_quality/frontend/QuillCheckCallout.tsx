import type { ReactNode } from 'react'

import { Button, Item, ItemActions, ItemContent, ItemDescription, ItemMedia, Spinner } from '@posthog/quill'

export interface QuillCheckCalloutAction {
    label: string
    onClick: () => void
    loading?: boolean
}

export interface QuillCheckCalloutProps {
    tone: 'info' | 'warning' | 'destructive' | 'success'
    children: ReactNode
    details?: ReactNode
    action?: QuillCheckCalloutAction
    busy?: boolean
}

export function QuillCheckCallout({ tone, children, details, action, busy }: QuillCheckCalloutProps): JSX.Element {
    return (
        <Item variant="outline" size="sm" tone={tone}>
            {busy && (
                <ItemMedia>
                    <Spinner />
                </ItemMedia>
            )}
            <ItemContent>
                <ItemDescription>{children}</ItemDescription>
                {details}
            </ItemContent>
            {action && (
                <ItemActions>
                    <Button variant="outline" onClick={action.onClick} loading={action.loading}>
                        {action.label}
                    </Button>
                </ItemActions>
            )}
        </Item>
    )
}

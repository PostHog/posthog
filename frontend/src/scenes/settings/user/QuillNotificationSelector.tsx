import { ReactNode } from 'react'

import { Button, Collapsible, CollapsibleContent, CollapsibleTrigger, Text } from '@posthog/quill'

export interface QuillNotificationBulkActions {
    enableLabel: string
    disableLabel: string
    onEnableAll: () => void
    onDisableAll: () => void
    disabledReason?: string
}

export function QuillNotificationSelector({
    title,
    expanded,
    onExpandedChange,
    hint,
    bulkActions,
    className,
    children,
}: {
    title: string
    expanded: boolean
    onExpandedChange: (expanded: boolean) => void
    hint?: string
    bulkActions?: QuillNotificationBulkActions
    className?: string
    children: ReactNode
}): JSX.Element {
    return (
        <Collapsible variant="folder" open={expanded} onOpenChange={onExpandedChange} className={className}>
            <CollapsibleTrigger>{title}</CollapsibleTrigger>
            <CollapsibleContent className="flex flex-col gap-2">
                {hint && (
                    <Text size="xs" variant="muted" className="m-0">
                        {hint}
                    </Text>
                )}
                {bulkActions && (
                    <div className="flex flex-wrap items-center gap-2">
                        <Button
                            variant="outline"
                            onClick={bulkActions.onEnableAll}
                            disabledReason={bulkActions.disabledReason}
                        >
                            {bulkActions.enableLabel}
                        </Button>
                        <Button
                            variant="outline"
                            onClick={bulkActions.onDisableAll}
                            disabledReason={bulkActions.disabledReason}
                        >
                            {bulkActions.disableLabel}
                        </Button>
                    </div>
                )}
                {children}
            </CollapsibleContent>
        </Collapsible>
    )
}

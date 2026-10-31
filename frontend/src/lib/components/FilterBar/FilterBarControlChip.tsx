import type { ComponentType, ReactNode } from 'react'

import { IconX } from '@posthog/icons'
import { Button, ButtonGroup, ButtonGroupText } from '@posthog/quill'

export interface FilterBarControlChipProps {
    icon: ComponentType<{ className?: string }>
    label: string
    children: ReactNode
    onRemove?: () => void
    'data-attr': string
}

export function FilterBarControlChip({
    icon: Icon,
    label,
    children,
    onRemove,
    'data-attr': dataAttr,
}: FilterBarControlChipProps): JSX.Element {
    return (
        <ButtonGroup className="max-w-full" data-attr={dataAttr}>
            <ButtonGroupText className="min-w-0 border border-border px-2">
                <Icon className="shrink-0" />
                <span className="truncate">{label}</span>
            </ButtonGroupText>
            {children}
            {onRemove && (
                <Button
                    size="icon"
                    variant="outline"
                    aria-label={`Remove ${label.toLowerCase()}`}
                    tooltip={`Remove ${label.toLowerCase()}`}
                    onClick={onRemove}
                    data-attr={`${dataAttr}-remove`}
                >
                    <IconX />
                </Button>
            )}
        </ButtonGroup>
    )
}

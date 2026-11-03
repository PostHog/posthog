import type { ComponentType, ReactNode } from 'react'

import { IconX } from '@posthog/icons'
import { Button, ButtonGroup } from '@posthog/quill'

import { FilterBarChipLabel } from './FilterBarChipLabel'

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
            <FilterBarChipLabel>
                <Icon className="shrink-0" />
                <span className="truncate">{label}</span>
            </FilterBarChipLabel>
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

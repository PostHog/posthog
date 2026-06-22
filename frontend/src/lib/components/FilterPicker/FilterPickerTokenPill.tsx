import { forwardRef, Fragment, MouseEvent } from 'react'

import { IconX } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { cn } from 'lib/utils/css-classes'

import { FilterPickerToken, FilterPickerTokenPart } from './FilterPicker.types'

function tokenText(parts: FilterPickerTokenPart[]): string {
    return parts.map((part) => part.ariaLabel ?? String(part.label)).join(' ')
}

export const FilterPickerTokenPill = forwardRef<
    HTMLDivElement,
    {
        token: FilterPickerToken
        onEdit?: () => void
        onRemove?: () => void
        className?: string
    }
>(function FilterPickerTokenPill({ token, onEdit, onRemove, className }, ref): JSX.Element {
    const label = tokenText(token.parts)
    const canEdit = token.editable !== false && !!onEdit
    const canRemove = token.removable === true || (token.removable !== false && (!!onRemove || !!token.onRemove))

    return (
        // data-orientation drives the button-group CSS that merges the buttons' shared border and corners,
        // so the remove button connects to the label instead of floating as a separate pill.
        <div
            ref={ref}
            role="group"
            data-quill
            data-slot="button-group"
            data-orientation="horizontal"
            className={cn('quill-button-group', className)}
        >
            <Button
                size="sm"
                variant="outline"
                className={cn('max-w-[16rem] justify-start font-semibold', !canEdit && 'cursor-default')}
                aria-label={canEdit ? `Edit filter: ${label}` : `Filter: ${label}`}
                title={token.title ?? label}
                onClick={canEdit ? onEdit : undefined}
            >
                <span className="flex min-w-0 items-center truncate">
                    {token.parts.map((part, index) => (
                        <Fragment key={part.key ?? index}>
                            {index > 0 && <span className="mx-0.5" aria-hidden />}
                            <span className="min-w-0 truncate">{part.label}</span>
                        </Fragment>
                    ))}
                </span>
            </Button>
            {canRemove && (
                <Button
                    aria-label={`Remove filter: ${label}`}
                    size="icon-sm"
                    variant="outline"
                    onClick={(event: MouseEvent) => {
                        event.stopPropagation()
                        ;(onRemove ?? token.onRemove)?.()
                    }}
                >
                    <IconX className="size-3.5" />
                </Button>
            )}
        </div>
    )
})

import { cva, type VariantProps } from 'class-variance-authority'
import * as React from 'react'
import { useMemo } from 'react'

import './field.css'
import { Label } from './label'
import { cn } from './lib/utils'
import { Separator } from './separator'

function FieldSet({ className, ...props }: React.ComponentProps<'fieldset'>): React.ReactElement {
    return (
        <fieldset
            data-slot="field-set"
            className={cn(
                'quill-field-set flex flex-col gap-4 has-[>[data-slot=checkbox-group]]:gap-3 has-[>[data-slot=radio-group]]:gap-3',
                className
            )}
            {...props}
        />
    )
}

function FieldLegend({
    className,
    variant = 'legend',
    ...props
}: React.ComponentProps<'legend'> & { variant?: 'legend' | 'label' }): React.ReactElement {
    return (
        <legend
            data-slot="field-legend"
            data-variant={variant}
            className={cn('quill-field-legend', className)}
            {...props}
        />
    )
}

function FieldGroup({ className, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return (
        <div
            data-slot="field-group"
            className={cn(
                'group/field-group @container/field-group flex w-full flex-col gap-4 data-[slot=checkbox-group]:gap-3 *:data-[slot=field-group]:gap-4',
                className
            )}
            {...props}
        />
    )
}

const fieldVariants = cva('quill-field group/field flex w-full gap-x-2 gap-y-1', {
    variants: {
        orientation: {
            vertical: 'flex-col *:w-full [&>.sr-only]:w-auto',
            horizontal:
                'flex-row items-center has-[>[data-slot=field-content]]:items-start *:data-[slot=field-label]:flex-auto has-[>[data-slot=field-content]]:[&>[role=checkbox],[role=radio]]:mt-px',
            responsive:
                'flex-col *:w-full @md/field-group:flex-row @md/field-group:items-center @md/field-group:*:w-auto @md/field-group:has-[>[data-slot=field-content]]:items-start @md/field-group:*:data-[slot=field-label]:flex-auto [&>.sr-only]:w-auto @md/field-group:has-[>[data-slot=field-content]]:[&>[role=checkbox],[role=radio]]:mt-px',
        },
    },
    defaultVariants: {
        orientation: 'vertical',
    },
})

function Field({
    className,
    orientation = 'vertical',
    ...props
}: React.ComponentProps<'div'> & VariantProps<typeof fieldVariants>): React.ReactElement {
    return (
        <div
            role="group"
            data-quill
            data-slot="field"
            data-orientation={orientation}
            className={cn(fieldVariants({ orientation }), className)}
            {...props}
        />
    )
}

function FieldContent({ className, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return (
        <div
            data-slot="field-content"
            className={cn('quill-field__content group/field-content flex flex-1 flex-col gap-0.5', className)}
            {...props}
        />
    )
}

function FieldLabel({ className, ...props }: React.ComponentProps<typeof Label>): React.ReactElement {
    return (
        <Label
            data-slot="field-label"
            className={cn('quill-field__label group/field-label peer/field-label flex w-fit gap-2', className)}
            {...props}
        />
    )
}

function FieldTitle({ className, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return (
        <div
            data-slot="field-label"
            className={cn('quill-field__title flex w-fit items-center gap-2', className)}
            {...props}
        />
    )
}

function FieldDescription({ className, ...props }: React.ComponentProps<'p'>): React.ReactElement {
    return (
        <p
            data-slot="field-description"
            className={cn('quill-field__description last:mt-0 nth-last-2:mt-0', className)}
            {...props}
        />
    )
}

function FieldSeparator({
    children,
    className,
    ...props
}: React.ComponentProps<'div'> & {
    children?: React.ReactNode
}): React.ReactElement {
    return (
        <div data-slot="field-separator" data-content={!!children} className={cn('quill-field__separator', className)} {...props}>
            <Separator className="absolute inset-0 top-1/2" />
            {children && (
                <span className="quill-field__separator-content" data-slot="field-separator-content">
                    {children}
                </span>
            )}
        </div>
    )
}

function FieldError({
    className,
    children,
    errors,
    ...props
}: React.ComponentProps<'div'> & {
    errors?: Array<{ message?: string } | undefined>
}): React.ReactElement | null {
    const content = useMemo(() => {
        if (children) {
            return children
        }

        if (!errors?.length) {
            return null
        }

        const uniqueErrors = [...new Map(errors.map((error) => [error?.message, error])).values()]

        if (uniqueErrors?.length == 1) {
            return uniqueErrors[0]?.message
        }

        return (
            <ul className="ms-4 flex list-disc flex-col gap-1">
                {uniqueErrors.map((error, index) => error?.message && <li key={index}>{error.message}</li>)}
            </ul>
        )
    }, [children, errors])

    if (!content) {
        return null
    }

    return (
        <div role="alert" data-slot="field-error" className={cn('quill-field__error', className)} {...props}>
            {content}
        </div>
    )
}

export {
    Field,
    FieldLabel,
    FieldDescription,
    FieldError,
    FieldGroup,
    FieldLegend,
    FieldSeparator,
    FieldSet,
    FieldContent,
    FieldTitle,
}

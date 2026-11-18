import { cva, type VariantProps } from 'class-variance-authority'
import * as React from 'react'
import { useMemo } from 'react'

import './field.css'
import { Label } from './label'
import { cn } from './lib/utils'
import { Separator } from './separator'

const FieldSet = React.forwardRef<HTMLFieldSetElement, React.ComponentProps<'fieldset'>>(function FieldSet(
    { className, ...props },
    ref
) {
    return (
        <fieldset
            ref={ref}
            data-slot="field-set"
            className={cn(
                'quill-field-set flex flex-col gap-4 has-[>[data-slot=checkbox-group]]:gap-3 has-[>[data-slot=radio-group]]:gap-3',
                className
            )}
            {...props}
        />
    )
})

const FieldLegend = React.forwardRef<
    HTMLLegendElement,
    React.ComponentProps<'legend'> & { variant?: 'legend' | 'label' }
>(function FieldLegend({ className, variant = 'legend', ...props }, ref) {
    return (
        <legend
            ref={ref}
            data-slot="field-legend"
            data-variant={variant}
            className={cn('quill-field-legend', className)}
            {...props}
        />
    )
})

const FieldGroup = React.forwardRef<HTMLDivElement, React.ComponentProps<'div'>>(function FieldGroup(
    { className, ...props },
    ref
) {
    return (
        <div
            ref={ref}
            data-slot="field-group"
            className={cn(
                'group/field-group @container/field-group flex w-full flex-col gap-4 data-[slot=checkbox-group]:gap-3 *:data-[slot=field-group]:gap-4',
                className
            )}
            {...props}
        />
    )
})

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

const Field = React.forwardRef<HTMLDivElement, React.ComponentProps<'div'> & VariantProps<typeof fieldVariants>>(
    function Field({ className, orientation = 'vertical', ...props }, ref) {
        return (
            <div
                ref={ref}
                role="group"
                data-quill
                data-slot="field"
                data-orientation={orientation}
                className={cn(fieldVariants({ orientation }), className)}
                {...props}
            />
        )
    }
)

const FieldContent = React.forwardRef<HTMLDivElement, React.ComponentProps<'div'>>(function FieldContent(
    { className, ...props },
    ref
) {
    return (
        <div
            ref={ref}
            data-slot="field-content"
            className={cn('quill-field__content group/field-content flex flex-1 flex-col gap-0.5', className)}
            {...props}
        />
    )
})

const FieldLabel = React.forwardRef<React.ComponentRef<typeof Label>, React.ComponentProps<typeof Label>>(
    function FieldLabel({ className, ...props }, ref) {
        return (
            <Label
                ref={ref}
                data-slot="field-label"
                className={cn('quill-field__label group/field-label peer/field-label flex w-fit gap-2', className)}
                {...props}
            />
        )
    }
)

const FieldTitle = React.forwardRef<HTMLDivElement, React.ComponentProps<'div'>>(function FieldTitle(
    { className, ...props },
    ref
) {
    return (
        <div
            ref={ref}
            data-slot="field-label"
            className={cn('quill-field__title flex w-fit items-center gap-2', className)}
            {...props}
        />
    )
})

const FieldDescription = React.forwardRef<HTMLParagraphElement, React.ComponentProps<'p'>>(function FieldDescription(
    { className, ...props },
    ref
) {
    return (
        <p
            ref={ref}
            data-slot="field-description"
            className={cn('quill-field__description last:mt-0 nth-last-2:mt-0', className)}
            {...props}
        />
    )
})

const FieldSeparator = React.forwardRef<
    HTMLDivElement,
    React.ComponentProps<'div'> & {
        children?: React.ReactNode
    }
>(function FieldSeparator({ children, className, ...props }, ref) {
    return (
        <div
            ref={ref}
            data-slot="field-separator"
            data-content={!!children}
            className={cn('quill-field__separator', className)}
            {...props}
        >
            <Separator className="absolute inset-0 top-1/2" />
            {children && (
                <span className="quill-field__separator-content" data-slot="field-separator-content">
                    {children}
                </span>
            )}
        </div>
    )
})

const FieldError = React.forwardRef<
    HTMLDivElement,
    React.ComponentProps<'div'> & {
        errors?: Array<{ message?: string } | undefined>
    }
>(function FieldError({ className, children, errors, ...props }, ref) {
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
        <div ref={ref} role="alert" data-slot="field-error" className={cn('quill-field__error', className)} {...props}>
            {content}
        </div>
    )
})

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

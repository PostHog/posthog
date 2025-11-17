import clsx from 'clsx'
import { Field as KeaField, FieldProps as KeaFieldProps } from 'kea-forms/lib/components'

import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { IconErrorOutline } from 'lib/lemon-ui/icons'
import { cn } from 'lib/utils/css-classes'

export type LemonPureFieldProps = {
    /** The label name to be displayed */
    label?: React.ReactNode
    /** Will show a muted (optional) next to the label */
    showOptional?: boolean
    /** Will show a clickable (what is this?) next to the label, useful if we want to toggle explanation modals on click */
    onExplanationClick?: () => void
    /** Info tooltip to be displayed next to the label */
    info?: React.ReactNode
    /** Help text to be shown directly beneath the input */
    help?: React.ReactNode
    /** Error message to be displayed */
    error?: React.ReactNode
    renderError?: (error: string) => React.ReactNode
    className?: string
    children?: React.ReactNode
    onClick?: () => void
    /** Flex the field as a row rather than columns */
    inline?: boolean
    /** The id of the input this field is for */
    htmlFor?: string
    /** The class name override for the label */
    labelClassName?: string
}

const LemonFieldError = ({ error }: { error: string }): JSX.Element => {
    return (
        <div className="text-danger flex items-center gap-1 text-sm">
            <IconErrorOutline className="text-xl shrink-0" /> {error}
        </div>
    )
}

const LemonPureField = ({
    label,
    info,
    error,
    help,
    htmlFor,
    showOptional,
    onExplanationClick,
    className,
    children,
    inline,
    onClick,
    renderError,
    labelClassName,
}: LemonPureFieldProps): JSX.Element => {
    return (
        <div
            onClick={onClick}
            className={cn(
                'Field flex',
                { 'gap-2': className ? className.indexOf('gap-') === -1 : true },
                className,
                error && 'Field--error',
                inline ? 'flex-row' : 'flex-col'
            )}
        >
            {label ? (
                <LemonLabel
                    info={info}
                    showOptional={showOptional}
                    onExplanationClick={onExplanationClick}
                    className={clsx(labelClassName, {
                        'cursor-pointer': !!onClick,
                    })}
                    htmlFor={htmlFor}
                >
                    {label}
                </LemonLabel>
            ) : null}
            {children}
            {help ? <div className="text-secondary text-xs">{help}</div> : null}
            {typeof error === 'string' ? renderError ? renderError(error) : <LemonFieldError error={error} /> : null}
        </div>
    )
}

export type LemonFieldProps = Omit<LemonPureFieldProps, 'children' | 'error'> & Pick<KeaFieldProps, 'children' | 'name'>

/** A field for use within a Kea form. Outside a form use `LemonField.Pure`. */
export const LemonField = ({
    name,
    help,
    className,
    showOptional,
    inline,
    info,
    renderError,
    labelClassName,
    ...keaFieldProps
}: LemonFieldProps): JSX.Element => {
    const template: KeaFieldProps['template'] = ({ label, kids, error }) => {
        return (
            <LemonPureField
                label={label}
                error={error}
                help={help}
                className={className}
                showOptional={showOptional}
                inline={inline}
                info={info}
                renderError={renderError}
                labelClassName={labelClassName}
            >
                {kids}
            </LemonPureField>
        )
    }
    return <KeaField {...keaFieldProps} name={name} template={template} noStyle />
}

/** A field without Kea form functionality. Within a form use `LemonField`. */
LemonField.Pure = LemonPureField
LemonField.Error = LemonFieldError

import clsx from 'clsx'
import { Field as KeaField, FieldProps as KeaFieldProps } from 'kea-forms/lib/components'
import { IconErrorOutline } from 'lib/lemon-ui/icons'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'

export type PureFieldProps = {
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
    className?: string
    children?: React.ReactNode
    onClick?: () => void
    /** Flex the field as a row rather than columns */
    inline?: boolean
    /** The id of the input this field is for */
    htmlFor?: string
}

/** A "Pure" field - used when you want the Field styles without the Kea form functionality */
export const PureField = ({
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
}: PureFieldProps): JSX.Element => {
    return (
        <div
            onClick={onClick}
            className={clsx('Field flex gap-2', className, error && 'Field--error', inline ? 'flex-row' : 'flex-col')}
        >
            {label ? (
                <LemonLabel
                    info={info}
                    showOptional={showOptional}
                    onExplanationClick={onExplanationClick}
                    className={clsx({
                        'cursor-pointer': !!onClick,
                    })}
                    htmlFor={htmlFor}
                >
                    {label}
                </LemonLabel>
            ) : null}
            {children}
            {help ? <div className="text-muted text-xs">{help}</div> : null}
            {error ? (
                <div className="text-danger flex items-center gap-1 text-sm">
                    <IconErrorOutline className="text-xl" /> {error}
                </div>
            ) : null}
        </div>
    )
}

export type FieldProps = Omit<PureFieldProps, 'children' | 'error'> & Pick<KeaFieldProps, 'children' | 'name'>

export const Field = ({
    name,
    help,
    className,
    showOptional,
    inline,
    info,
    ...keaFieldProps
}: FieldProps): JSX.Element => {
    /** Drop-in replacement antd template for kea forms */
    const template: KeaFieldProps['template'] = ({ label, kids, error }) => {
        return (
            <PureField
                label={label}
                error={error}
                help={help}
                className={className}
                showOptional={showOptional}
                inline={inline}
                info={info}
            >
                {kids}
            </PureField>
        )
    }
    return <KeaField {...keaFieldProps} name={name} template={template} noStyle />
}

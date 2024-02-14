import clsx from 'clsx'
import { Field as KeaField, FieldProps as KeaFieldProps } from 'kea-forms/lib/components'
import { IconErrorOutline } from 'lib/lemon-ui/icons'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'

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
    className?: string
    children?: React.ReactNode
    onClick?: () => void
    /** Flex the field as a row rather than columns */
    inline?: boolean
    /** The id of the input this field is for */
    htmlFor?: string
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
}: LemonPureFieldProps): JSX.Element => {
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

export type LemonFieldProps = Omit<LemonPureFieldProps, 'children' | 'error'> & Pick<KeaFieldProps, 'children' | 'name'>

/** A field for use within a Kea form. Outside a form use `LemonField.Pure`. */
export const LemonField = ({
    name,
    help,
    className,
    showOptional,
    inline,
    info,
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
            >
                {kids}
            </LemonPureField>
        )
    }
    return <KeaField {...keaFieldProps} name={name} template={template} noStyle />
}

/** A field without Kea form functionality. Within a form use `LemonField`. */
LemonField.Pure = LemonPureField

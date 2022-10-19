import { IconErrorOutline } from 'lib/components/icons'
import { LemonLabel } from '../components/LemonLabel/LemonLabel'
import { Field as KeaField, FieldProps as KeaFieldProps } from 'kea-forms/lib/components'
import clsx from 'clsx'

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
}

/** A "Pure" field - used when you want the Field styles without the Kea form functionality */
export const PureField = ({
    label,
    info,
    error,
    help,
    showOptional,
    onExplanationClick,
    className,
    children,
    onClick,
}: PureFieldProps): JSX.Element => {
    return (
        <div onClick={onClick} className={clsx('Field flex flex-col gap-2', className, error && 'Field--error')}>
            {label ? (
                <LemonLabel
                    info={info}
                    showOptional={showOptional}
                    onExplanationClick={onExplanationClick}
                    className={clsx({
                        'cursor-pointer': !!onClick,
                    })}
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

export const Field = ({ name, help, className, showOptional, ...keaFieldProps }: FieldProps): JSX.Element => {
    /** Drop-in replacement antd template for kea forms */
    const template: KeaFieldProps['template'] = ({ label, kids, error }) => {
        return (
            <PureField label={label} error={error} help={help} className={className} showOptional={showOptional}>
                {kids}
            </PureField>
        )
    }
    return <KeaField {...keaFieldProps} name={name} template={template} noStyle />
}

import { IconErrorOutline } from 'lib/components/icons'
import React from 'react'
import { LemonLabel } from '../components/LemonLabel/LemonLabel'
import { Field as KeaField, FieldProps as KeaFieldProps } from 'kea-forms/lib/components'

export type PureFieldProps = {
    /** The label name to be displayed */
    label?: React.ReactNode
    /** Info tooltip to be displayed next to the label */
    info?: React.ReactNode
    /** Help text to be shown directly beneath the input */
    help?: React.ReactNode
    /** Error message to be displayed */
    error?: React.ReactNode
    children?: React.ReactNode
}

/** A "Pure" field - used when you want the Field styles without the Kea form functionality */
export const PureField = ({ label, info, error, help, children }: PureFieldProps): JSX.Element => {
    return (
        <div className="flex flex-col gap-2">
            {label ? <LemonLabel info={info}>{label}</LemonLabel> : null}
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

export const Field = ({ name, help, ...keaFieldProps }: FieldProps): JSX.Element => {
    /** Drop-in replacement antd template for kea forms */
    const template: KeaFieldProps['template'] = ({ label, kids, error }) => {
        return (
            <PureField label={label} error={error} help={help}>
                {kids}
            </PureField>
        )
    }
    return <KeaField {...keaFieldProps} name={name} template={template} noStyle />
}

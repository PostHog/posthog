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

export const PureField = ({ label, info, error, help, children }: PureFieldProps): JSX.Element => {
    return (
        <div className="flex flex-col gap-2">
            {label ? <LemonLabel info={info}>{label}</LemonLabel> : null}
            {children}
            {help ? <div className="text-muted">{help}</div> : null}
            {error ? (
                <div className="text-danger flex items-center gap-1">
                    <IconErrorOutline className="text-xl" /> {error}
                </div>
            ) : null}
        </div>
    )
}

export type FieldProps = Omit<PureFieldProps, 'children' | 'error'> & KeaFieldProps

export const Field = ({ name, ...keaFieldProps }: FieldProps): JSX.Element => {
    /** Drop-in replacement antd template for kea forms */
    const template: FieldProps['template'] = ({ label, kids, error }) => {
        console.log({ label, kids, error })
        return (
            <PureField label={label} error={error}>
                {kids}
            </PureField>
        )
    }
    return <KeaField {...keaFieldProps} name={name} template={template} />
}

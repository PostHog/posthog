import { FieldProps as KeaFieldProps } from 'kea-forms'
import clsx from 'clsx'
import { Field as KeaField } from 'kea-forms/lib/components'
import React from 'react'

export interface FieldProps extends KeaFieldProps {
    showOptional?: boolean
}

/** Compatible replacement for Form.Item */
export const Field = ({ showOptional, name, ...keaFieldProps }: FieldProps): JSX.Element => {
    /** Drop-in replacement antd template for kea forms */
    const template: FieldProps['template'] = ({ label, kids, hint, error }) => {
        return (
            <div
                className={clsx(
                    'ant-row',
                    'ant-form-item',
                    hint || error ? 'ant-form-item-with-help' : '',
                    error ? `ant-form-item-has-error` : ''
                )}
            >
                {label ? (
                    <div className="ant-col ant-form-item-label">
                        <label htmlFor={String(name)} title={typeof label === 'string' ? label : undefined}>
                            {showOptional ? (
                                <>
                                    {label}
                                    {showOptional ? (
                                        <span className="ant-form-item-optional" title="">
                                            (optional)
                                        </span>
                                    ) : null}
                                </>
                            ) : (
                                label
                            )}
                        </label>
                    </div>
                ) : null}
                <div className="ant-col ant-form-item-control">
                    <div className="ant-form-item-control-input">
                        <div className="ant-form-item-control-input-content">{kids}</div>
                    </div>
                    {hint || error ? (
                        <div className="ant-form-item-explain ant-form-item-explain-connected">
                            {error ? (
                                <div role="alert" className="ant-form-item-explain-error">
                                    Error: {error}
                                </div>
                            ) : null}
                            {hint ? (
                                <div role="alert" className="ant-form-item-explain-warning">
                                    Hint: {hint}
                                </div>
                            ) : null}
                        </div>
                    ) : null}
                </div>
            </div>
        )
    }

    return <KeaField {...keaFieldProps} name={name} template={template} />
}

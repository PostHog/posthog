import { Form, Input } from 'antd'
import { FormItemProps } from 'antd/es/form'
import React, { lazy, Suspense } from 'react'

import { ExclamationCircleFilled } from '@ant-design/icons'

const PasswordStrength = lazy(() => import('../../lib/components/PasswordStrength'))

interface PasswordInputProps extends FormItemProps {
    showStrengthIndicator?: boolean
    label?: string
    style?: React.CSSProperties
    validateMinLength?: boolean
}

export const PasswordInput = React.forwardRef(function PasswordInputInternal(
    { label = 'Password', showStrengthIndicator, validateMinLength, style, ...props }: PasswordInputProps,
    ref: React.LegacyRef<Input>
): JSX.Element {
    return (
        <div style={style}>
            <div style={{ display: 'flex', alignItems: 'center' }}>
                <label htmlFor="password" className="ant-form-item-label">
                    {label}
                </label>
                {showStrengthIndicator && (
                    <Form.Item
                        shouldUpdate={(prevValues, currentValues) => prevValues.password !== currentValues.password}
                        style={{ margin: 0, flexGrow: 1, paddingBottom: 8 }}
                    >
                        {({ getFieldValue }) => (
                            <Suspense fallback={<></>}>
                                <div style={{ display: 'flex', overflow: 'hidden', whiteSpace: 'nowrap' }}>
                                    <PasswordStrength password={getFieldValue('password')} />
                                </div>
                            </Suspense>
                        )}
                    </Form.Item>
                )}
            </div>

            <Form.Item
                name="password"
                rules={[
                    {
                        required: true,
                        message: (
                            <>
                                <ExclamationCircleFilled style={{ marginLeft: 4 }} /> Please enter your password to
                                continue
                            </>
                        ),
                    },
                    {
                        min: validateMinLength ? 8 : undefined,
                        message: (
                            <>
                                <ExclamationCircleFilled style={{ marginLeft: 4 }} /> Password must be at least 8
                                characters
                            </>
                        ),
                    },
                ]}
                validateTrigger={['onSubmit']}
                style={showStrengthIndicator ? { marginBottom: 0 } : undefined}
                {...props}
            >
                <Input
                    ref={ref}
                    className="ph-ignore-input"
                    type="password"
                    data-attr="password"
                    placeholder="••••••••••"
                />
            </Form.Item>
            {showStrengthIndicator && (
                <Form.Item shouldUpdate style={{ margin: 0, flexGrow: 1, paddingBottom: 8 }}>
                    {({ getFieldError }) =>
                        !getFieldError('password')?.length && (
                            <div className="text-muted text-small mb mt-025">
                                Passwords must be at least 8 characters
                            </div>
                        )
                    }
                </Form.Item>
            )}
        </div>
    )
})

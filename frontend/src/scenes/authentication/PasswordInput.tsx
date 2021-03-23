import { Form, Input } from 'antd'
import { FormItemProps } from 'antd/es/form'
import React, { lazy, Suspense } from 'react'

const PasswordStrength = lazy(() => import('../../lib/components/PasswordStrength'))

interface PasswordInputProps extends FormItemProps {
    showStrengthIndicator?: boolean
    label?: string
}

export function PasswordInput({
    label = 'Password',
    showStrengthIndicator,
    ...props
}: PasswordInputProps): JSX.Element {
    return (
        <>
            <Form.Item
                name="password"
                label={label}
                rules={[
                    {
                        required: true,
                        message: 'Please enter your password to continue',
                    },
                ]}
                style={showStrengthIndicator ? { marginBottom: 0 } : undefined}
                {...props}
            >
                <Input className="ph-ignore-input" type="password" data-attr="login-password" placeholder="********" />
            </Form.Item>
            {showStrengthIndicator && (
                <Form.Item shouldUpdate={(prevValues, currentValues) => prevValues.password !== currentValues.password}>
                    {({ getFieldValue }) => (
                        <Suspense fallback={<></>}>
                            <PasswordStrength password={getFieldValue('password')} />
                        </Suspense>
                    )}
                </Form.Item>
            )}
        </>
    )
}

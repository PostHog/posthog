import { Form, Input } from 'antd'
import { FormItemProps } from 'antd/es/form'
import React, { lazy, Suspense } from 'react'

const PasswordStrength = lazy(() => import('../../lib/components/PasswordStrength'))

interface PasswordInputProps extends FormItemProps {
    showStrengthIndicator?: boolean
    label?: string
    style?: React.CSSProperties
    validateMinLength?: boolean
}

export function PasswordInput({
    label = 'Password',
    showStrengthIndicator,
    validateMinLength,
    style,
    ...props
}: PasswordInputProps): JSX.Element {
    return (
        <div style={style}>
            <Form.Item
                name="password"
                label={label}
                rules={[
                    {
                        required: true,
                        message: `Please enter your ${label.toLowerCase()} to continue`,
                    },
                    {
                        min: validateMinLength ? 8 : undefined,
                        message: `Your ${label.toLowerCase()} must be at least 8 characters long`,
                    },
                ]}
                style={showStrengthIndicator ? { marginBottom: 0 } : undefined}
                {...props}
            >
                <Input className="ph-ignore-input" type="password" data-attr="password" placeholder="********" />
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
        </div>
    )
}

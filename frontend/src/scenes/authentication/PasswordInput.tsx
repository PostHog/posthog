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
            <Form.Item
                name="password"
                label={label}
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
                                <ExclamationCircleFilled style={{ marginLeft: 4 }} /> Your password must be at least 8
                                characters long
                            </>
                        ),
                    },
                ]}
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
})

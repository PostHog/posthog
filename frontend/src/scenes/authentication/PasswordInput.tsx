import { Form, Input } from 'antd'
import React, { lazy, Suspense } from 'react'

const PasswordStrength = lazy(() => import('../../lib/components/PasswordStrength'))

export function PasswordInput({ showStrengthIndicator }: { showStrengthIndicator?: boolean }): JSX.Element {
    return (
        <>
            <Form.Item
                name="password"
                label="Password"
                rules={[
                    {
                        required: true,
                        message: 'Please enter your password to continue',
                    },
                ]}
                style={showStrengthIndicator ? { marginBottom: 0 } : undefined}
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

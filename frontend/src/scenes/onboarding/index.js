import React, { useState, useRef, lazy, Suspense } from 'react'
import { useActions, useValues } from 'kea'
import { signupLogic } from './logic'
import hedgehogBlue from 'public/hedgehog-blue.png'
import posthogLogo from 'public/posthog-icon.svg'
import { Row, Space, Button, Input, Checkbox } from 'antd'
import { fromParams } from 'lib/utils'
const PasswordStrength = lazy(() => import('../../lib/components/PasswordStrength'))

function Signup() {
    const [state, setState] = useState({ submitted: false })
    const [formState, setFormState] = useState({
        firstName: {},
        companyName: {},
        email: {},
        password: {},
        emailOptIn: { value: true },
    })
    const passwordInput = useRef(null)
    const { createAccount } = useActions(signupLogic)
    const { accountLoading } = useValues(signupLogic)
    const { plan } = fromParams()

    const updateForm = (name, target, valueAttr = 'value') => {
        /* Validate password (if applicable) */
        if (name === 'password') {
            let password = target[valueAttr]
            const valid = password.length >= 8
            setFormState({ ...formState, password: { ...formState.password, valid, value: target[valueAttr] } })
        } else {
            setFormState({ ...formState, [name]: { ...formState[name], value: target[valueAttr] } })
        }
    }

    const handleSubmit = (e) => {
        e.preventDefault()
        setState({ ...state, submitted: true })

        /* Password has custom validation */
        if (!formState.password.valid) {
            passwordInput.current.focus()
            return
        }
        const payload = {
            first_name: formState.firstName.value,
            company_name: formState.companyName.value || undefined,
            email: formState.email.value,
            password: formState.password.value,
            email_opt_in: formState.emailOptIn.value,
            plan, // Pass it along if on QS, won't have any effect unless on multitenancy
        }
        createAccount(payload)
    }

    return (
        <div className="signup-form">
            <Space direction="vertical" className="space-top" style={{ width: '100%', paddingLeft: 32 }}>
                <h1 className="title" style={{ marginBottom: 0, display: 'flex', alignItems: 'center' }}>
                    <img src={posthogLogo} alt="" style={{ height: 60 }} /> Create your account
                </h1>
                <div className="page-caption">Understand your users. Build a better product.</div>
            </Space>
            <Row style={{ display: 'flex', justifyContent: 'center' }}>
                <div style={{ display: 'flex', alignItems: 'center', flexDirection: 'column' }}>
                    <img
                        src={hedgehogBlue}
                        style={{ maxHeight: '100%', maxWidth: 300, marginTop: 64 }}
                        alt=""
                        className="main-img"
                    />
                </div>
                <div
                    style={{
                        display: 'flex',
                        justifyContent: 'flex-start',
                        margin: '0 32px',
                        flexDirection: 'column',
                        paddingTop: 32,
                        maxWidth: '32rem',
                    }}
                >
                    <form onSubmit={handleSubmit}>
                        <div className="input-set">
                            <label htmlFor="signupEmail">Email</label>
                            <Input
                                placeholder="jane@hogflix.io"
                                type="email"
                                value={formState.email.value}
                                onChange={(e) => updateForm('email', e.target)}
                                required
                                disabled={accountLoading}
                                id="signupEmail"
                            />
                        </div>

                        <div className={`input-set ${state.submitted && !formState.password.valid ? 'errored' : ''}`}>
                            <label htmlFor="signupPassword">Password</label>
                            <Input.Password
                                value={formState.password.value}
                                onChange={(e) => updateForm('password', e.target)}
                                required
                                ref={passwordInput}
                                disabled={accountLoading}
                                id="signupPassword"
                            />
                            <Suspense fallback={<span />}>
                                <PasswordStrength password={formState.password.value} />
                            </Suspense>
                            {!formState.password.valid && (
                                <span className="caption">Your password must have at least 8 characters.</span>
                            )}
                        </div>

                        <div className="input-set">
                            <label htmlFor="signupFirstName">First Name</label>
                            <Input
                                placeholder="Jane"
                                autoFocus
                                value={formState.firstName.value}
                                onChange={(e) => updateForm('firstName', e.target)}
                                required
                                disabled={accountLoading}
                                id="signupFirstName"
                            />
                        </div>

                        <div className="input-set">
                            <label htmlFor="signupCompanyName">Company or Project</label>
                            <Input
                                placeholder="Hogflix Movies"
                                value={formState.companyName.value}
                                onChange={(e) => updateForm('companyName', e.target)}
                                disabled={accountLoading}
                                id="signupCompanyName"
                            />
                        </div>

                        <div>
                            <Checkbox
                                checked={formState.emailOptIn.value}
                                onChange={(e) => updateForm('emailOptIn', e.target, 'checked')}
                                disabled={accountLoading}
                            >
                                Send me occasional emails about security and product updates. You may unsubscribe at any
                                time.
                            </Checkbox>
                        </div>
                        <div className="text-center space-top">
                            <Button
                                type="primary"
                                htmlType="submit"
                                data-attr="signup"
                                disabled={state.submitted && !formState.password.valid}
                                loading={accountLoading}
                            >
                                Create my account
                            </Button>
                        </div>

                        <div style={{ color: '#666666', marginBottom: 60, textAlign: 'center' }} className="space-top">
                            By clicking the button above you agree to our{' '}
                            <a href="https://posthog.com/terms" target="_blank">
                                Terms of Service
                            </a>{' '}
                            and{' '}
                            <a href="https://posthog.com/privacy" target="_blank">
                                Privacy Policy
                            </a>
                            .
                        </div>
                    </form>
                </div>
            </Row>
        </div>
    )
}

export default Signup

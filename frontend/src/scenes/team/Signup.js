import React, { useState, useRef, useEffect } from 'react'
import { useActions, useValues } from 'kea'
import { signupLogic } from './signupLogic'
import hedgehogBlue from './../../../public/hedgehog-blue.jpg'
import posthogLogo from './../../../public/posthog-icon.svg'
import { Row, Col, Space, Button, Input, Checkbox } from 'antd'

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
    const logic = signupLogic()
    const { createAccount } = useActions(logic)
    const { account, accountLoading } = useValues(logic)

    const updateForm = (name, target, valueAttr = 'value') => {
        /* Validate password (if applicable) */
        if (name === 'password') {
            const valid = target[valueAttr].length >= 8
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
        }
        createAccount(payload)
    }

    useEffect(() => {
        if (account && Object.keys(account).length > 0) window.location.href = '/'
    }, [account])

    return (
        <>
            <Space direction="vertical" className="space-top" style={{ width: '100%', paddingLeft: 32 }}>
                <h1 className="title" style={{ marginBottom: 0 }}>
                    <img src={posthogLogo} alt="" style={{ height: 60 }} /> Create your account
                </h1>
                <div className="page-caption">Understand your users. Build a better product.</div>
            </Space>
            <Row style={{ display: 'flex', justifyContent: 'center' }}>
                <div
                    style={{ display: 'flex', alignItems: 'center', flexDirection: 'column', justifyContent: 'center' }}
                >
                    <img src={hedgehogBlue} style={{ maxHeight: '100%' }} alt="" />
                </div>
                <div
                    style={{
                        display: 'flex',
                        justifyContent: 'flex-start',
                        margin: '0 32px',
                        flexDirection: 'column',
                        paddingTop: 32,
                    }}
                >
                    <form onSubmit={handleSubmit}>
                        <Row gutter={[16, 16]}>
                            <Col span={12}>
                                <div className="ph-input-group">
                                    <label>Name</label>
                                    <Input
                                        placeholder="John"
                                        autoFocus
                                        value={formState.firstName.value}
                                        onChange={(e) => updateForm('firstName', e.target)}
                                        required
                                        disabled={accountLoading}
                                    />
                                </div>
                            </Col>
                            <Col span={12}>
                                <div className="ph-input-group">
                                    <label>Company or Project</label>
                                    <Input
                                        placeholder="Rocket Rides"
                                        value={formState.companyName.value}
                                        onChange={(e) => updateForm('companyName', e.target)}
                                        disabled={accountLoading}
                                    />
                                </div>
                            </Col>
                        </Row>
                        <Row gutter={[16, 16]}>
                            <Col span={12}>
                                <div className="ph-input-group">
                                    <label>Email</label>
                                    <Input
                                        placeholder="john@posthog.com"
                                        type="email"
                                        value={formState.email.value}
                                        onChange={(e) => updateForm('email', e.target)}
                                        required
                                        disabled={accountLoading}
                                    />
                                    <span className="caption">This will be your username.</span>
                                </div>
                            </Col>
                            <Col span={12}>
                                <div
                                    className={`ph-input-group ${
                                        state.submitted && !formState.password.valid ? 'errored' : ''
                                    }`}
                                >
                                    <label>Password</label>
                                    <Input.Password
                                        placeholder="********"
                                        value={formState.password.value}
                                        onChange={(e) => updateForm('password', e.target)}
                                        required
                                        ref={passwordInput}
                                        disabled={accountLoading}
                                    />
                                    <span className="caption">At least 8 characters.</span>
                                </div>
                            </Col>
                        </Row>
                        <div>
                            <Checkbox
                                checked={formState.emailOptIn.value}
                                onChange={(e) => updateForm('emailOptIn', e.target, 'checked')}
                                disabled={accountLoading}
                            >
                                Send me emails about security and product updates (unsubscribe at any time).
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

                        <div style={{ color: '#666666', marginBottom: 60 }} className="space-top">
                            By tapping the button above you agree to our{' '}
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
        </>
    )
}

export default Signup

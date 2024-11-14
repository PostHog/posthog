import '~/styles'
import './Exporter.scss'

import clsx from 'clsx'
import { Form } from 'kea-forms'
import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { useRef } from 'react'
import { ERROR_MESSAGES } from 'scenes/authentication/Login'
import { loginLogic } from 'scenes/authentication/loginLogic'
import { SupportModalButton } from 'scenes/authentication/SupportModalButton'

export function ExporterLogin(): JSX.Element {
    const generalError: any = null
    const passwordInputRef = useRef<HTMLInputElement>(null)
    const isPasswordHidden = false
    const isLoginSubmitting = false

    return (
        <BridgePage
            view="login"
            hedgehog
            message={
                <>
                    Welcome to
                    <br /> PostHog!
                </>
            }
            footer={<SupportModalButton />}
        >
            <div className="space-y-4">
                <h2>Access share</h2>
                {generalError && (
                    <LemonBanner type="error">
                        {generalError.detail || ERROR_MESSAGES[generalError.code] || (
                            <>
                                Could not complete your login.
                                <br />
                                Please try again.
                            </>
                        )}
                    </LemonBanner>
                )}
                <Form logic={loginLogic} formKey="login" enableFormOnSubmit className="space-y-4">
                    <div className={clsx('PasswordWrapper', isPasswordHidden && 'zero-height')}>
                        <LemonField
                            name="password"
                            label={
                                <div className="flex flex-1 items-center justify-between gap-2">
                                    <span>Password</span>
                                </div>
                            }
                        >
                            <LemonInput
                                type="password"
                                inputRef={passwordInputRef}
                                className="ph-ignore-input"
                                data-attr="password"
                                placeholder="••••••••••"
                                autoComplete="current-password"
                            />
                        </LemonField>
                    </div>

                    <LemonButton
                        type="primary"
                        status="alt"
                        htmlType="submit"
                        data-attr="password-login"
                        fullWidth
                        center
                        loading={isLoginSubmitting}
                        size="large"
                    >
                        Log in
                    </LemonButton>
                </Form>
                <div className="text-center mt-4">Don't have a password? Ask the person who shared this with you!</div>
            </div>
        </BridgePage>
    )
}

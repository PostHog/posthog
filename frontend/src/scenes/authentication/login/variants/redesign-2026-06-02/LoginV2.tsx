import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Field as FormField, Form } from 'kea-forms'
import { router } from 'kea-router'
import { type ChangeEvent, useEffect, useRef, useState } from 'react'

import { getCookie } from 'lib/api'
import { DisguiseHog } from 'lib/components/hedgehogs'
import { SSOEnforcedLoginButton, SocialLoginButtons } from 'lib/components/SocialLoginButton/SocialLoginButton'
import { CLOUD_HOSTNAMES } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Link } from 'lib/lemon-ui/Link'
import {
    Button,
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
    Field,
    FieldError,
    FieldLabel,
    Input,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from 'lib/ui/quill'
import { KeyboardGardenBackground } from 'scenes/authentication/shared/KeyboardGardenBackground'
import { ERROR_MESSAGES } from 'scenes/authentication/shared/loginErrorMessages'
import { RedirectIfLoggedInOtherInstance } from 'scenes/authentication/shared/RedirectToLoggedInInstance'
import { SupportModalButton } from 'scenes/authentication/shared/SupportModalButton'
import { WelcomeLogo } from 'scenes/authentication/shared/WelcomeLogo'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { urls } from 'scenes/urls'

import { LoginMethod, Region } from '~/types'

import { loginLogic } from '../../loginLogic'

const LAST_LOGIN_METHOD_COOKIE = 'ph_last_login_method'

function LoginDataRegion(): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)

    if (!preflight?.cloud || !preflight?.region) {
        return null
    }

    const navigateToRegion = (region: Region | null): void => {
        if (!region) {
            return
        }
        const { pathname, search, hash } = router.values.currentLocation
        window.location.href = `https://${CLOUD_HOSTNAMES[region]}${pathname}${search}${hash}`
    }

    return (
        <Field>
            <FieldLabel>
                Data region{' '}
                <Link to="https://posthog.com/docs/getting-started/cloud" target="_blank" className="font-normal">
                    (what's this?)
                </Link>
            </FieldLabel>
            <Select value={preflight.region} onValueChange={navigateToRegion}>
                <SelectTrigger className="w-full">
                    <SelectValue />
                </SelectTrigger>
                <SelectContent>
                    <SelectItem value={Region.US}>United States</SelectItem>
                    <SelectItem value={Region.EU}>European Union</SelectItem>
                </SelectContent>
            </Select>
        </Field>
    )
}

export function LoginV2(): JSX.Element {
    const { precheck, clearGeneralError, resetLogin, resendEmailMFA } = useActions(loginLogic)
    const {
        precheckResponse,
        precheckResponseLoading,
        login,
        isLoginSubmitting,
        generalError,
        signupUrl,
        resendResponseLoading,
    } = useValues(loginLogic)
    const { preflight } = useValues(preflightLogic)

    const passwordInputRef = useRef<HTMLInputElement>(null)
    const preventPasswordError = useRef(false)
    const wasPasswordHiddenRef = useRef(true)
    const [loginHovered, setLoginHovered] = useState(false)

    const isPasswordHidden = precheckResponse.status === 'pending' || !!precheckResponse.sso_enforcement
    const isEmailVerificationSent = generalError?.code === 'email_verification_sent'
    const loginTitle = isEmailVerificationSent ? 'Check your email' : 'Log in'
    const lastLoginMethod = getCookie(LAST_LOGIN_METHOD_COOKIE) as LoginMethod

    useEffect(() => {
        const wasPasswordHidden = wasPasswordHiddenRef.current
        wasPasswordHiddenRef.current = isPasswordHidden
        if (!isPasswordHidden) {
            passwordInputRef.current?.focus()
        } else if (!wasPasswordHidden) {
            resetLogin()
        }
    }, [isPasswordHidden, resetLogin])

    return (
        <KeyboardGardenBackground>
            <div className="flex w-full max-w-[24rem] flex-col px-4">
                <WelcomeLogo view="login" />
                <div className="relative w-full">
                    <DisguiseHog
                        aria-hidden
                        draggable={false}
                        className={clsx(
                            'pointer-events-none absolute right-0 top-1/2 z-0 w-64 -translate-y-1/2 select-none transition-transform duration-300 ease-out motion-reduce:transition-none',
                            loginHovered ? 'translate-x-[45%] rotate-8' : 'translate-x-0'
                        )}
                    />
                    <Card className="relative z-10 w-full">
                        <CardHeader>
                            <CardTitle className="text-center text-xl">{loginTitle}</CardTitle>
                            {!isEmailVerificationSent && (
                                <CardDescription className="text-center">The hogs missed you.</CardDescription>
                            )}
                        </CardHeader>
                        <CardContent className="flex flex-col gap-4">
                            {preflight?.cloud && <RedirectIfLoggedInOtherInstance />}
                            {generalError && (
                                <LemonBanner type={isEmailVerificationSent ? 'warning' : 'error'}>
                                    {generalError.detail || ERROR_MESSAGES[generalError.code] || (
                                        <>
                                            Could not complete your login.
                                            <br />
                                            Please try again.
                                        </>
                                    )}
                                </LemonBanner>
                            )}
                            {isEmailVerificationSent ? (
                                <div className="flex flex-col items-center gap-2">
                                    <Button
                                        variant="outline"
                                        size="sm"
                                        disabled={resendResponseLoading}
                                        onClick={() => resendEmailMFA(null)}
                                    >
                                        Resend verification email
                                    </Button>
                                    <Link onClick={() => clearGeneralError()} className="text-secondary">
                                        Back to login
                                    </Link>
                                </div>
                            ) : (
                                <Form
                                    logic={loginLogic}
                                    formKey="login"
                                    enableFormOnSubmit
                                    onSubmitCapture={(e) => {
                                        if (isPasswordHidden || preventPasswordError.current) {
                                            e.preventDefault()
                                            e.stopPropagation()
                                            preventPasswordError.current = false
                                        }
                                    }}
                                    className="flex flex-col gap-4"
                                >
                                    <LoginDataRegion />
                                    <FormField name="email">
                                        {({ value, onChange, error, id }) => (
                                            <Field>
                                                <FieldLabel htmlFor={id}>Email</FieldLabel>
                                                <Input
                                                    id={id}
                                                    type="email"
                                                    autoFocus
                                                    className="ph-ignore-input"
                                                    placeholder="email@yourcompany.com"
                                                    value={value ?? ''}
                                                    onChange={(e: ChangeEvent<HTMLInputElement>) =>
                                                        onChange(e.target.value)
                                                    }
                                                    onBlur={() => precheck({ email: login.email })}
                                                    aria-invalid={!!error}
                                                />
                                                {error && <FieldError>{error}</FieldError>}
                                            </Field>
                                        )}
                                    </FormField>
                                    {!isPasswordHidden && (
                                        <FormField name="password">
                                            {({ value, onChange, error, id }) => (
                                                <Field>
                                                    <FieldLabel htmlFor={id}>
                                                        <div className="flex w-full items-center justify-between gap-2">
                                                            <span>Password</span>
                                                            <Link
                                                                to={[urls.passwordReset(), { email: login.email }]}
                                                                className="font-normal"
                                                                tabIndex={-1}
                                                            >
                                                                Forgot your password?
                                                            </Link>
                                                        </div>
                                                    </FieldLabel>
                                                    <Input
                                                        id={id}
                                                        ref={passwordInputRef}
                                                        type="password"
                                                        className="ph-ignore-input"
                                                        placeholder="••••••••••"
                                                        autoComplete="current-password"
                                                        value={value ?? ''}
                                                        onChange={(e: ChangeEvent<HTMLInputElement>) =>
                                                            onChange(e.target.value)
                                                        }
                                                        aria-invalid={!!error}
                                                    />
                                                    {error && <FieldError>{error}</FieldError>}
                                                </Field>
                                            )}
                                        </FormField>
                                    )}
                                    {!precheckResponse.sso_enforcement && (
                                        <Button
                                            type="submit"
                                            variant="primary"
                                            className="w-full"
                                            disabled={isLoginSubmitting || precheckResponseLoading}
                                            onMouseEnter={() => setLoginHovered(true)}
                                            onMouseLeave={() => setLoginHovered(false)}
                                            onMouseDown={() => {
                                                if (isPasswordHidden) {
                                                    preventPasswordError.current = true
                                                }
                                            }}
                                        >
                                            Log in
                                        </Button>
                                    )}
                                    {precheckResponse.sso_enforcement && (
                                        <SSOEnforcedLoginButton
                                            provider={precheckResponse.sso_enforcement}
                                            email={login.email}
                                            isLastUsed={lastLoginMethod === precheckResponse.sso_enforcement}
                                        />
                                    )}
                                    {precheckResponse.saml_available && !precheckResponse.sso_enforcement && (
                                        <SSOEnforcedLoginButton
                                            provider="saml"
                                            email={login.email}
                                            isLastUsed={lastLoginMethod === 'saml'}
                                        />
                                    )}
                                </Form>
                            )}
                            {!isEmailVerificationSent && preflight?.cloud && (
                                <div className="text-center text-sm">
                                    Don't have an account?{' '}
                                    <Link to={[signupUrl, { email: login.email }]} className="font-semibold">
                                        Create an account
                                    </Link>
                                </div>
                            )}
                            {!isEmailVerificationSent &&
                                !precheckResponse.saml_available &&
                                !precheckResponse.sso_enforcement && (
                                    <SocialLoginButtons
                                        caption="Or log in with"
                                        topDivider
                                        lastUsedProvider={lastLoginMethod}
                                        showPasskey
                                    />
                                )}
                        </CardContent>
                    </Card>
                </div>
                <div className="mt-4 flex justify-center">
                    <SupportModalButton />
                </div>
            </div>
        </KeyboardGardenBackground>
    )
}

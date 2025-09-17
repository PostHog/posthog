import '../scenes/authentication/Login.scss'

import clsx from 'clsx'
import { actions, kea, path, reducers, useValues } from 'kea'
import { Form, forms } from 'kea-forms'

import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { ERROR_MESSAGES } from 'scenes/authentication/Login'
import { SupportModalButton } from 'scenes/authentication/SupportModalButton'

import type { loginLogicType } from './ExporterLoginType'

export interface LoginForm {
    password: string
}

export const loginLogic = kea<loginLogicType>([
    path(['exporter', 'ExporterLogin']),
    actions({
        setGeneralError: (code: string, detail: string) => ({ code, detail }),
        clearGeneralError: true,
        setSuccess: true,
    }),
    reducers({
        generalError: [
            null as { code: string; detail: string } | null,
            {
                setGeneralError: (_, error) => error,
                clearGeneralError: () => null,
                setSuccess: () => null, // Clear error on success
            },
        ],
        isSuccess: [
            false,
            {
                setSuccess: () => true,
                clearGeneralError: () => false,
            },
        ],
    }),
    forms(({ actions }) => ({
        login: {
            defaults: { password: '' } as LoginForm,
            errors: ({ password }) => ({
                password: !password ? 'Please enter your password to continue' : undefined,
            }),
            submit: async ({ password }, breakpoint) => {
                breakpoint()
                const response = await fetch(window.location.href, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ password }),
                })
                if (response.status === 200) {
                    actions.setSuccess()
                    window.location.reload()
                } else {
                    actions.setGeneralError(response.statusText, (await response.json()).error)
                }
            },
        },
    })),
])

export interface ExporterLoginProps {
    whitelabel?: boolean
}

export function ExporterLogin(props: ExporterLoginProps): JSX.Element {
    const { isLoginSubmitting, generalError, isSuccess } = useValues(loginLogic())

    const login = (
        <div className="space-y-4">
            <h2>Access share</h2>
            {generalError && (
                <LemonBanner type="error">
                    {generalError.detail || ERROR_MESSAGES[generalError.code] || (
                        <>
                            Could not unlock the content.
                            <br />
                            Please try again.
                        </>
                    )}
                </LemonBanner>
            )}
            <Form logic={loginLogic} formKey="login" enableFormOnSubmit className="space-y-4">
                <div className={clsx('PasswordWrapper')}>
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
                            className="ph-ignore-input"
                            data-attr="password"
                            placeholder="••••••••••"
                            autoComplete="current-password"
                        />
                    </LemonField>
                </div>

                <LemonButton
                    type="primary"
                    status={isSuccess ? 'default' : 'alt'}
                    htmlType="submit"
                    data-attr="password-login"
                    fullWidth
                    center
                    loading={isLoginSubmitting && !isSuccess}
                    size="large"
                >
                    {isSuccess ? 'Access granted!' : 'Unlock'}
                </LemonButton>
            </Form>
            <div className="text-center mt-4">Don't have a password? Ask the person who shared this with you!</div>
        </div>
    )

    if (props.whitelabel) {
        return (
            <BridgePage noLogo view="login" footer={<SupportModalButton />}>
                {login}
            </BridgePage>
        )
    }

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
            {login}
        </BridgePage>
    )
}

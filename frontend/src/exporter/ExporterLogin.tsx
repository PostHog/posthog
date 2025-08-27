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

import { Exporter } from '~/exporter/Exporter'
import { ExportedData } from '~/exporter/types'

import type { loginLogicType } from './ExporterLoginType'

export interface LoginForm {
    password: string
}

export const loginLogic = kea<loginLogicType>([
    path(['exporter', 'ExporterLogin']),
    actions({
        setGeneralError: (code: string, detail: string) => ({ code, detail }),
        clearGeneralError: true,
        setData: (data: any) => ({ data }),
    }),
    reducers({
        data: [
            null as ExportedData | null,
            {
                setData: (_, { data }) => data,
            },
        ],
        // This is separate from the login form, so that the form can be submitted even if a general error is present
        generalError: [
            null as { code: string; detail: string } | null,
            {
                setGeneralError: (_, error) => error,
                clearGeneralError: () => null,
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
                if (response.status == 200) {
                    const data = await response.json()

                    // If we have a shareToken, make XHR request with JWT to get dashboard data
                    if (data.shareToken) {
                        try {
                            const dashboardResponse = await fetch(window.location.href, {
                                method: 'GET',
                                headers: {
                                    Authorization: `Bearer ${data.shareToken}`,
                                    Accept: 'application/json',
                                },
                            })

                            if (dashboardResponse.ok) {
                                const dashboardData = await dashboardResponse.json()

                                // CRITICAL: Set up API configuration BEFORE setting data
                                // This ensures the config is ready before Exporter component mounts
                                try {
                                    const { ApiConfig } = await import('lib/api')

                                    // Set POSTHOG_APP_CONTEXT if it's provided in the response
                                    if (dashboardData.app_context) {
                                        window.POSTHOG_APP_CONTEXT = dashboardData.app_context

                                        if (dashboardData.app_context.current_team) {
                                            ApiConfig.setCurrentTeamId(dashboardData.app_context.current_team.id)
                                            ApiConfig.setCurrentProjectId(
                                                dashboardData.app_context.current_team.project_id
                                            )

                                            // Trigger teamLogic to reload with the new context
                                            try {
                                                const { teamLogic } = await import('scenes/teamLogic')
                                                teamLogic.actions.loadCurrentTeam()
                                            } catch (error) {
                                                console.warn('Could not reload teamLogic:', error)
                                            }
                                        }

                                        if (dashboardData.app_context.current_user?.organization?.id) {
                                            ApiConfig.setCurrentOrganizationId(
                                                dashboardData.app_context.current_user.organization.id
                                            )
                                        } else if (dashboardData.app_context.current_organization?.id) {
                                            // Try current_organization as alternative
                                            ApiConfig.setCurrentOrganizationId(
                                                dashboardData.app_context.current_organization.id
                                            )
                                        }
                                    } else {
                                        // This should not happen once backend is updated
                                        console.error('WARNING: app_context not provided in JWT response!')
                                        console.error(
                                            'The backend should include app_context with the same structure as POSTHOG_APP_CONTEXT'
                                        )

                                        // Fallback: use dashboard team_id if app_context not provided
                                        if (dashboardData.dashboard?.team_id) {
                                            ApiConfig.setCurrentTeamId(dashboardData.dashboard.team_id)
                                            ApiConfig.setCurrentProjectId(dashboardData.dashboard.team_id)
                                        } else {
                                            console.error('No team data available in response!')
                                        }
                                    }
                                } catch (error) {
                                    console.error('Failed to set API configuration:', error)
                                    actions.setGeneralError(
                                        'Configuration error',
                                        'Failed to initialize application context'
                                    )
                                    return
                                }

                                // Ensure we have all required data before proceeding
                                if (!dashboardData.dashboard) {
                                    console.error('No dashboard in response:', dashboardData)
                                    actions.setGeneralError('Invalid response', 'Dashboard data is missing')
                                    return
                                }

                                // Use small delay to ensure API config changes have propagated
                                // before mounting the Exporter component and making API calls
                                setTimeout(() => {
                                    actions.setData(dashboardData)
                                }, 10)
                            } else {
                                actions.setGeneralError(
                                    'Failed to load dashboard',
                                    'Unable to access dashboard with provided token'
                                )
                            }
                        } catch {
                            actions.setGeneralError('Network error', 'Unable to load dashboard data')
                        }
                        return
                    }
                    actions.setData(data)
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
    const { data, isLoginSubmitting, generalError } = useValues(loginLogic())

    // Only render Exporter if we have data AND the API config is properly set
    if (data && window.POSTHOG_APP_CONTEXT?.current_team) {
        return <Exporter {...data} />
    }

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
                    status="alt"
                    htmlType="submit"
                    data-attr="password-login"
                    fullWidth
                    center
                    loading={isLoginSubmitting}
                    size="large"
                >
                    Unlock
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

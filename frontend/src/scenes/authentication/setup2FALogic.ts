import { kea, path, connect, afterMount, listeners, actions, reducers, props } from 'kea'
import { loaders } from 'kea-loaders'
import { forms } from 'kea-forms'
import api from 'lib/api'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { lemonToast } from '@posthog/lemon-ui'

import type { setup2FALogicType } from './setup2FALogicType'

export interface TwoFactorForm {
    token: number | null
}

export interface Setup2FALogicProps {
    onSuccess?: () => void
}

export const setup2FALogic = kea<setup2FALogicType>([
    path(['scenes', 'authentication', 'loginLogic']),
    props({} as Setup2FALogicProps),
    connect({
        values: [preflightLogic, ['preflight'], featureFlagLogic, ['featureFlags']],
    }),
    actions({
        setGeneralError: (code: string, detail: string) => ({ code, detail }),
        clearGeneralError: true,
        setup: true,
    }),
    reducers({
        // This is separate from the login form, so that the form can be submitted even if a general error is present
        generalError: [
            null as { code: string; detail: string } | null,
            {
                setGeneralError: (_, error) => error,
                clearGeneralError: () => null,
            },
        ],
    }),
    loaders(() => ({
        startSetup: [
            {},
            {
                setup: async (_, breakpoint) => {
                    await breakpoint()
                    await api.get('api/users/@me/start_2fa_setup/')
                    return { status: 'completed' }
                },
            },
        ],
    })),
    forms(({ actions }) => ({
        token: {
            defaults: { token: null } as TwoFactorForm,
            errors: ({ token }) => ({
                token: !token ? 'Please enter a token to continue' : undefined,
            }),
            submit: async ({ token }, breakpoint) => {
                await breakpoint()
                try {
                    return await api.create('api/users/@me/validate_2fa/', { token })
                } catch (e) {
                    const { code } = e as Record<string, any>
                    const { detail } = e as Record<string, any>
                    actions.setGeneralError(code, detail)
                    throw e
                }
            },
        },
    })),
    listeners(({ props }) => ({
        submitTokenSuccess: () => {
            lemonToast.success('2FA method added successfully')
            props.onSuccess && props.onSuccess()
        },
    })),

    afterMount(({ actions }) => actions.setup()),
])

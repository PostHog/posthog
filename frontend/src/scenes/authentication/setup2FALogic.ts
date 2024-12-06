import { lemonToast } from '@posthog/lemon-ui'
import { actions, afterMount, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import type { setup2FALogicType } from './setup2FALogicType'

export interface TwoFactorForm {
    token: number | null
}

export interface TwoFactorStatus {
    is_enabled: boolean
    backup_codes: string[]
    method: string | null
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
        loadStatus: true,
        generateBackupCodes: true,
    }),
    reducers({
        generalError: [
            null as { code: string; detail: string } | null,
            {
                setGeneralError: (_, error) => error,
                clearGeneralError: () => null,
            },
        ],
        status: [
            null as TwoFactorStatus | null,
            {
                loadStatusSuccess: (_, { status }) => status,
                generateBackupCodesSuccess: (state, { generatingCodes }) => {
                    if (!state) {
                        return null
                    }
                    return {
                        ...state,
                        // Fallback to current backup codes if generating codes fails
                        backup_codes: generatingCodes?.backup_codes || state.backup_codes,
                    }
                },
            },
        ],
    }),
    selectors({
        is2FAEnabled: [(s) => [s.status], (status): boolean => !!status?.is_enabled],
    }),
    loaders(() => ({
        startSetup: [
            {},
            {
                setup: async (_, breakpoint) => {
                    breakpoint()
                    await api.get('api/users/@me/start_2fa_setup/')
                    return { status: 'completed' }
                },
            },
        ],
        status: [
            null as TwoFactorStatus | null,
            {
                loadStatus: async () => {
                    return await api.get('api/users/@me/two_factor_status/')
                },
            },
        ],
        generatingCodes: [
            null as { backup_codes: string[] } | null,
            {
                generateBackupCodes: async () => {
                    return await api.create<any>('api/users/@me/two_factor_backup_codes/')
                },
            },
        ],
        disable2FA: [
            false,
            {
                disable2FA: async () => {
                    try {
                        await api.create<any>('api/users/@me/two_factor_disable/')
                        return true
                    } catch (e) {
                        const { code, detail } = e as Record<string, any>
                        throw { code, detail }
                    }
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
                breakpoint()
                try {
                    return await api.create<any>('api/users/@me/validate_2fa/', { token })
                } catch (e) {
                    const { code, detail } = e as Record<string, any>
                    actions.setGeneralError(code, detail)
                    throw e
                }
            },
        },
    })),
    listeners(({ props, actions }) => ({
        submitTokenSuccess: () => {
            lemonToast.success('2FA method added successfully')
            actions.loadStatus()
            props.onSuccess?.()
        },
        disable2FASuccess: () => {
            lemonToast.success('2FA disabled successfully')
        },
        generateBackupCodesSuccess: () => {
            lemonToast.success('Backup codes generated successfully')
        },
    })),

    afterMount(({ actions }) => {
        actions.setup()
        actions.loadStatus()
    }),
])

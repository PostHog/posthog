import { actions, afterMount, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { membersLogic } from 'scenes/organization/membersLogic'
import { userLogic } from 'scenes/userLogic'

import type { twoFactorLogicType } from './twoFactorLogicType'

export interface TwoFactorForm {
    token: number | null
}

export interface TwoFactorStatus {
    is_enabled: boolean
    backup_codes: string[]
    method: string | null
}

export interface TwoFactorLogicProps {
    onSuccess?: () => void
}

export const twoFactorLogic = kea<twoFactorLogicType>([
    path(['scenes', 'authentication', 'loginLogic']),
    props({} as TwoFactorLogicProps),
    connect(() => ({
        values: [preflightLogic, ['preflight'], featureFlagLogic, ['featureFlags'], userLogic, ['user']],
        actions: [userLogic, ['loadUser'], membersLogic, ['loadAllMembers']],
    })),
    actions({
        setGeneralError: (code: string, detail: string) => ({ code, detail }),
        clearGeneralError: true,
        loadStatus: true,
        generateBackupCodes: true,
        disable2FA: true,
        openTwoFactorSetupModal: (forceOpen?: boolean) => ({ forceOpen }),
        closeTwoFactorSetupModal: true,
        toggleDisable2FAModal: (open: boolean) => ({ open }),
        toggleBackupCodesModal: (open: boolean) => ({ open }),
        setSetupCallOngoing: (ongoing: boolean) => ({ ongoing }),
    }),
    reducers({
        isTwoFactorSetupModalOpen: [
            false,
            {
                openTwoFactorSetupModal: () => true,
                closeTwoFactorSetupModal: () => false,
            },
        ],
        forceOpenTwoFactorSetupModal: [
            false,
            {
                openTwoFactorSetupModal: (_, { forceOpen }) => !!forceOpen,
                closeTwoFactorSetupModal: () => false,
            },
        ],
        isDisable2FAModalOpen: [
            false,
            {
                toggleDisable2FAModal: (_, { open }) => open,
            },
        ],
        isBackupCodesModalOpen: [
            false,
            {
                toggleBackupCodesModal: (_, { open }) => open,
            },
        ],
        generalError: [
            null as { code: string; detail: string } | null,
            {
                setGeneralError: (_, error) => error,
                clearGeneralError: () => null,
            },
        ],
        setupCallState: [
            { isOngoing: false } as { isOngoing: boolean },
            {
                setSetupCallOngoing: (_, { ongoing }) => ({ isOngoing: ongoing }),
                startSetupSuccess: (state) => ({ ...state, isOngoing: false }),
                startSetupFailure: (state) => ({ ...state, isOngoing: false }),
                closeTwoFactorSetupModal: (state) => ({ ...state, isOngoing: false }),
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
        canSwitchOrg: [(s) => [s.user], (user): boolean => (user?.organizations || []).length > 1],
    }),
    loaders(({ values, actions }) => ({
        startSetup: [
            null as { secret: string; success: boolean } | null,
            {
                openTwoFactorSetupModal: async (_, breakpoint) => {
                    const { isOngoing } = values.setupCallState

                    if (isOngoing) {
                        return values.startSetup
                    }

                    // We need this to prevent triggering the setup API call multiple times, which breaks the flow
                    actions.setSetupCallOngoing(true)

                    breakpoint()
                    const response = await api.get('api/users/@me/two_factor_start_setup/')
                    return response
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
                    return await api.create<any>('api/users/@me/two_factor_validate/', { token })
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
        disable2FA: async () => {
            try {
                await api.create<any>('api/users/@me/two_factor_disable/')
                lemonToast.success('2FA disabled successfully. The page will reload.')
                actions.loadStatus()

                // Reload to avoid breaking calls on the page if enforce_2fa=True
                setTimeout(() => {
                    window.location.reload()
                }, 3000)
            } catch (e) {
                const { code, detail } = e as Record<string, any>
                actions.setGeneralError(code, detail)
                throw e
            }
        },
        generateBackupCodesSuccess: () => {
            lemonToast.success('Backup codes generated successfully')
        },
        closeTwoFactorSetupModal: () => {
            // Clear the form when closing the modal
            actions.resetToken()
        },
    })),

    afterMount(({ actions, values }) => {
        actions.loadStatus()

        if (
            values.user &&
            values.user.organization?.enforce_2fa &&
            !values.user.is_2fa_enabled &&
            !values.user.is_impersonated &&
            !values.user.has_social_auth &&
            !values.user.has_sso_enforcement
        ) {
            actions.openTwoFactorSetupModal(true)
        }
    }),
])

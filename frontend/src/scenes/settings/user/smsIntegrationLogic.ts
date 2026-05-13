import { actions, events, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import {
    usersSmsDestroy,
    usersSmsList,
    usersSmsStartVerificationCreate,
    usersSmsVerifyCreate,
} from '~/generated/core/api'
import type { SMSIntegrationItemApi } from '~/generated/core/api.schemas'

import type { smsIntegrationLogicType } from './smsIntegrationLogicType'

export const smsIntegrationLogic = kea<smsIntegrationLogicType>([
    path(['scenes', 'settings', 'user', 'smsIntegrationLogic']),

    actions({
        startVerification: (phoneNumber: string) => ({ phoneNumber }),
        verificationStarted: (phoneNumber: string) => ({ phoneNumber }),
        verifyCode: (phoneNumber: string, code: string) => ({ phoneNumber, code }),
        verificationCompleted: true,
        cancelVerification: true,
        removePhone: (phoneNumber: string) => ({ phoneNumber }),
    }),

    reducers({
        pendingPhoneNumber: [
            null as string | null,
            {
                verificationStarted: (_, { phoneNumber }) => phoneNumber,
                verificationCompleted: () => null,
                cancelVerification: () => null,
            },
        ],
        startingVerification: [
            false,
            {
                startVerification: () => true,
                verificationStarted: () => false,
                cancelVerification: () => false,
            },
        ],
        verifyingCode: [
            false,
            {
                verifyCode: () => true,
                verificationCompleted: () => false,
                cancelVerification: () => false,
            },
        ],
    }),

    loaders({
        sms: [
            [] as SMSIntegrationItemApi[],
            {
                loadSMS: async () => {
                    return await usersSmsList('@me')
                },
            },
        ],
    }),

    listeners(({ actions }) => ({
        startVerification: async ({ phoneNumber }) => {
            try {
                const response = await usersSmsStartVerificationCreate('@me', { phone_number: phoneNumber })
                lemonToast.success(`Verification code sent to ${response.phone_number}`)
                actions.verificationStarted(response.phone_number)
            } catch (error: unknown) {
                actions.cancelVerification()
                const detail = error instanceof Error && 'detail' in error ? (error as any).detail : undefined
                lemonToast.error(detail || 'Could not send verification code.')
            }
        },
        verifyCode: async ({ phoneNumber, code }) => {
            try {
                await usersSmsVerifyCreate('@me', { phone_number: phoneNumber, code })
                lemonToast.success('Phone number verified.')
                actions.verificationCompleted()
                actions.loadSMS()
            } catch (error: unknown) {
                actions.verificationCompleted()
                const detail = error instanceof Error && 'detail' in error ? (error as any).detail : undefined
                lemonToast.error(detail || 'Could not verify code.')
            }
        },
        removePhone: async ({ phoneNumber }) => {
            try {
                await usersSmsDestroy('@me', encodeURIComponent(phoneNumber))
                lemonToast.success('Phone number removed.')
                actions.loadSMS()
            } catch {
                lemonToast.error('Could not remove phone number.')
            }
        },
    })),

    events(({ actions }) => ({
        afterMount: () => {
            actions.loadSMS()
        },
    })),
])

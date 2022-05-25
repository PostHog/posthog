import api from 'lib/api'
import { kea } from 'kea'
import { licenseLogicType } from './licenseLogicType'
import { APIErrorType, LicensePlan, LicenseType } from '~/types'
import { preflightLogic } from '../../PreflightCheck/preflightLogic'
import { lemonToast } from 'lib/components/lemonToast'
import { dayjs } from 'lib/dayjs'

export function isLicenseExpired(license: LicenseType): boolean {
    return new Date(license.valid_until) < new Date()
}

/** The higher the plan, the higher its sorting value - sync with back-end License model */
const PLAN_TO_SORTING_VALUE: Record<LicensePlan, number> = { [LicensePlan.Scale]: 10, [LicensePlan.Enterprise]: 20 }

export const licenseLogic = kea<licenseLogicType>({
    path: ['scenes', 'instance', 'Licenses', 'licenseLogic'],
    connect: {
        values: [preflightLogic, ['preflight']],
    },
    actions: {
        setError: (error: APIErrorType | null) => ({ error }),
        addLicense: (license: LicenseType) => ({ license }),
        setShowConfirmCancel: (license: LicenseType | null) => ({ license }),
    },
    loaders: ({ values, actions }) => ({
        licenses: [
            [] as LicenseType[],
            {
                loadLicenses: async () => {
                    return values.preflight?.cloud ? [] : (await api.licenses.list()).results
                },
                createLicense: async ({ key }: { key: string }) => {
                    try {
                        const license = await api.licenses.create(key)
                        lemonToast.success(
                            `Activated license – you can now use all features of the ${license.plan} plan. Refreshing the page...`
                        )
                        actions.setError(null)
                        setTimeout(() => {
                            window.location.reload() // Permissions, projects etc will be out of date at this point, so refresh
                        }, 4000)
                        return [license, ...values.licenses]
                    } catch (response) {
                        actions.setError(response as APIErrorType)
                        return values.licenses
                    }
                },
                deleteLicense: async ({ id }: LicenseType) => {
                    try {
                        await api.licenses.delete(id)
                        actions.setShowConfirmCancel(null)
                        lemonToast.success(`Your license was deactivated. Refreshing the page...`)
                        actions.setError(null)
                        setTimeout(() => {
                            window.location.reload() // Permissions, projects etc will be out of date at this point, so refresh
                        }, 4000)
                        return values.licenses.filter((license: LicenseType) => license.id != id)
                    } catch (response) {
                        lemonToast.error(
                            (response as APIErrorType).detail ||
                                'We were unable to automatically cancel your license. Please contact sales@posthog.com for support.'
                        )
                        return values.licenses
                    }
                },
            },
        ],
    }),
    reducers: {
        licenses: {
            addLicense: (state, { license }) => [license, ...state],
        },
        error: [
            null as null | APIErrorType,
            {
                setError: (_, { error }) => error,
            },
        ],
        showConfirmCancel: [
            null as null | LicenseType,
            {
                setShowConfirmCancel: (_, { license }) => license,
            },
        ],
    },
    selectors: {
        relevantLicense: [
            (s) => [s.licenses],
            (licenses): LicenseType | null => {
                // KEEP IN SYNC FOR WITH LicenseManager.first_valid FOR THE ACTIVE LICENSE
                // We determine the most relevant license to be the top one that's still active
                // OR the one that expired most recently
                if (licenses.length === 0) {
                    return null
                }
                const validLicenses = licenses.filter((license) => !isLicenseExpired(license))
                if (validLicenses.length > 0) {
                    return validLicenses.sort(
                        (a, b) => PLAN_TO_SORTING_VALUE[b.plan] - PLAN_TO_SORTING_VALUE[a.plan]
                    )[0]
                }
                const expiredLicenses = licenses.slice()
                return expiredLicenses.sort((a, b) => dayjs(b.valid_until).diff(dayjs(a.valid_until)))[0]
            },
        ],
    },
    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadLicenses()
        },
    }),
})

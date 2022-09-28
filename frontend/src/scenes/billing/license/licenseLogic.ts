import api from 'lib/api'
import { actions, afterMount, connect, kea, path, reducers, selectors } from 'kea'
import type { licenseLogicType } from './licenseLogicType'
import { APIErrorType, LicensePlan, LicenseType } from '~/types'
import { preflightLogic } from '../../PreflightCheck/preflightLogic'
import { lemonToast } from 'lib/components/lemonToast'
import { dayjs } from 'lib/dayjs'
import { loaders } from 'kea-loaders'
import { forms } from 'kea-forms'
import { organizationLogic } from 'scenes/organizationLogic'
import { isEmail, toParams } from 'lib/utils'
import { userLogic } from 'scenes/userLogic'
import { router } from 'kea-router'

export function isLicenseExpired(license: LicenseType): boolean {
    return new Date(license.valid_until) < new Date()
}

/** The higher the plan, the higher its sorting value - sync with back-end License model */
const PLAN_TO_SORTING_VALUE: Record<LicensePlan, number> = { [LicensePlan.Scale]: 10, [LicensePlan.Enterprise]: 20 }

export const licenseLogic = kea<licenseLogicType>([
    path(['scenes', 'instance', 'Licenses', 'licenseLogic']),
    connect({
        values: [preflightLogic, ['preflight'], organizationLogic, ['currentOrganization'], userLogic, ['user']],
    }),
    actions({
        addLicense: (license: LicenseType) => ({ license }),
        setShowConfirmCancel: (license: LicenseType | null) => ({ license }),
        setShowLicenseDirectInput: (show: boolean) => ({ show }),
    }),
    loaders(({ values, actions }) => ({
        licenses: [
            [] as LicenseType[],
            {
                loadLicenses: async () => {
                    return (await api.licenses.list()).results
                },
                deleteLicense: async ({ id }: LicenseType) => {
                    try {
                        await api.licenses.delete(id)
                        actions.setShowConfirmCancel(null)
                        lemonToast.success(`Your license was deactivated. Refreshing the page...`)
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
    })),
    forms(({ actions, values }) => ({
        activateLicense: {
            defaults: { key: '' } as { key: string },
            errors: ({ key }) => ({
                key: !key ? 'Please enter your license key' : undefined,
            }),
            submit: async ({ key }, breakpoint) => {
                breakpoint(500)
                try {
                    const license = await api.licenses.create(key)
                    lemonToast.success(
                        `Activated license - you can now use all features of the ${license.plan} plan. Refreshing the page...`
                    )
                    // Reset the URL so we don't trigger the license submission again
                    router.actions.replace('/instance/licenses')
                    setTimeout(() => {
                        window.location.reload() // Permissions, projects etc will be out of date at this point, so refresh
                    }, 4000)

                    actions.loadLicensesSuccess([license, ...values.licenses])
                } catch (e: any) {
                    actions.setActivateLicenseManualErrors({
                        key: e.detail || 'License could not be activated. Please contact support.',
                    })
                    throw e
                }
            },
        },

        createLicense: {
            defaults: {
                client_name: values.currentOrganization?.name,
                billing_email: values.user?.email,
                terms: false,
            } as {
                client_name: string
                billing_email: string
                terms: boolean
            },
            errors: ({ client_name, billing_email, terms }) => ({
                client_name: !client_name
                    ? 'Please enter the name of your organisation for billing purposes'
                    : undefined,
                billing_email: !billing_email
                    ? 'Please enter the email to be associated with the license'
                    : !isEmail(billing_email)
                    ? 'Please enter a valid email address'
                    : undefined,
                terms: !terms ? 'You must accept the terms and conditions to continue' : undefined,
            }),
            submit: async (params) => {
                window.location.href =
                    'https://license.posthog.com/start-payment?' +
                    toParams({
                        return_url: window.location.origin + '/instance/licenses',
                        ...params,
                    })
            },
        },
    })),
    reducers({
        licenses: {
            addLicense: (state, { license }) => [license, ...state],
        },
        showConfirmCancel: [
            null as null | LicenseType,
            {
                setShowConfirmCancel: (_, { license }) => license,
            },
        ],
        showLicenseDirectInput: [
            false,
            {
                setShowLicenseDirectInput: (_, { show }) => show,
            },
        ],
    }),
    selectors({
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
    }),
    afterMount(({ actions }) => {
        actions.loadLicenses()
    }),
])

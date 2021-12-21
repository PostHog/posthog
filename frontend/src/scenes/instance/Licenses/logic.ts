import api from 'lib/api'
import { kea } from 'kea'
import { toast } from 'react-toastify'
import { licenseLogicType } from './logicType'
import { APIErrorType, LicenseType } from '~/types'
import { preflightLogic } from '../../PreflightCheck/logic'
import { isLicenseExpired } from '.'

export const licenseLogic = kea<licenseLogicType>({
    path: ['scenes', 'instance', 'Licenses', 'licenseLogic'],
    connect: {
        values: [preflightLogic, ['preflight']],
    },
    actions: {
        setError: (error: APIErrorType | null) => ({ error }),
        addLicense: (license: LicenseType) => ({ license }),
    },
    loaders: ({ values, actions }) => ({
        licenses: [
            [] as LicenseType[],
            {
                loadLicenses: async () => {
                    return values.preflight?.cloud ? [] : (await api.get('api/license')).results
                },
                createLicense: async (payload: { key: string }) => {
                    try {
                        const license = (await api.create('api/license', payload)) as LicenseType
                        toast(
                            `Your license key was succesfully activated. You can now use all the features in the ${license.plan} plan.`
                        )
                        actions.setError(null)
                        return [license, ...values.licenses]
                    } catch (response) {
                        actions.setError(response as APIErrorType)
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
    },
    selectors: {
        relevantLicense: [
            (s) => [s.licenses],
            (licenses): LicenseType | undefined => {
                // We determine the most relevant license to be the one that's still active OR the one addded last
                return licenses.find((license) => !isLicenseExpired(license)) || licenses[licenses.length - 1]
            },
        ],
    },
    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadLicenses()
        },
    }),
})

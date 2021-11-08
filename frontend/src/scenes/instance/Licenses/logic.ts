import api from 'lib/api'
import { kea } from 'kea'
import { toast } from 'react-toastify'
import { licenseLogicType } from './logicType'
import { APIErrorType, LicenseType } from '~/types'
import { preflightLogic } from '../../PreflightCheck/logic'

export const licenseLogic = kea<licenseLogicType>({
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
    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadLicenses()
        },
    }),
})

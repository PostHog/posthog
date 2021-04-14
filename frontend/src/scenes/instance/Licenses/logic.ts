import api from 'lib/api'
import { kea } from 'kea'
import { toast } from 'react-toastify'
import { licenseLogicType } from './logicType'
import { APIErrorType } from '~/types'
interface License {
    key: string
}

export const licenseLogic = kea<licenseLogicType<License, APIErrorType>>({
    actions: {
        setError: (error: Error) => ({ error }),
        addLicense: (license: License) => ({ license }),
        createLicense: (license: License) => ({ license }),
    },
    loaders: {
        licenses: [
            [],
            {
                loadLicenses: async () => {
                    return (await api.get('api/license')).results
                },
            },
        ],
    },
    reducers: {
        licenses: {
            addLicense: (state: Array<License>, { license }) => [license, ...state],
        },
        error: [
            null as null | APIErrorType,
            {
                setError: (_, { error }) => error,
            },
        ],
    },

    listeners: ({ actions }) => ({
        createLicense: async (license: License) => {
            let new_license: License | null = null
            try {
                new_license = await api.create('api/license', license.license)
            } catch (response) {
                actions.setError(response as APIErrorType)
                return
            }
            toast(
                `Your license key was succesfully activated. You can now use all the features in the ${new_license.plan} plan.`
            )
            actions.addLicense(new_license)
            actions.setError(null)
        },
    }),
    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadLicenses()
        },
    }),
})

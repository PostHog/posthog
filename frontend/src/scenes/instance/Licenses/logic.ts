import api from 'lib/api'
import { kea } from 'kea'
import { toast } from 'react-toastify'
import { licenseLogicType } from './logicType'

interface Error {
    detail: string
    code: string
}

interface License {
    key: string
}

export const licenseLogic = kea<licenseLogicType<License, Error>>({
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
            false,
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
                actions.setError(response)
                return
            }
            toast(
                `Your license key was succesfully activated. You can now use all the features in the ${new_license.plan} plan.`
            )
            actions.addLicense(new_license)
            actions.setError(false)
        },
    }),
    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadLicenses()
        },
    }),
})

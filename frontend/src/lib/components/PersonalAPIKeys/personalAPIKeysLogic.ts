import { kea } from 'kea'
import { toast } from 'react-toastify'
import api from 'lib/api'
import { PersonalAPIKeyType } from '~/types'
import { personalAPIKeysLogicType } from 'types/lib/components/PersonalAPIKeys/personalAPIKeysLogicType.ts'
import { copyToClipboard } from 'lib/utils'

export const personalAPIKeysLogic = kea<personalAPIKeysLogicType<PersonalAPIKeyType>>({
    loaders: ({ values }) => ({
        keys: [
            [] as PersonalAPIKeyType[],
            {
                loadKeys: async () => {
                    const response: PersonalAPIKeyType[] = await api.get('api/personal_api_keys/')
                    return response
                },
                createKey: async (label: string) => {
                    const newKey: PersonalAPIKeyType = await api.create('api/personal_api_keys/', { label })
                    return [newKey, ...values.keys]
                },
                deleteKey: async (key: PersonalAPIKeyType) => {
                    await api.delete(`api/personal_api_keys/${key.id}/`)
                    return (values.keys as PersonalAPIKeyType[]).filter((filteredKey) => filteredKey.id != key.id)
                },
            },
        ],
    }),
    reducers: {
        latestKey: [
            null as PersonalAPIKeyType | null,
            {
                createKeySuccess: (_, { keys }) => keys[0],
            },
        ],
    },
    listeners: () => ({
        createKeySuccess: ({ keys }: { keys: PersonalAPIKeyType[] }) => {
            toast.success(`Personal API key "${keys[0].label}" created.`)
            copyToClipboard(keys[0].value)
        },
        deleteKeySuccess: ({}: { keys: PersonalAPIKeyType[] }) => {
            toast.success(`Personal API key deleted.`)
        },
    }),

    events: ({ actions }) => ({
        afterMount: [actions.loadKeys],
    }),
})

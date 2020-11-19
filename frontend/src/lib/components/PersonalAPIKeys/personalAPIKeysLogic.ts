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
                    const response: PersonalAPIKeyType[] = await api.get('api/projects/@current/personal-api-keys/')
                    return response
                },
                createKey: async (label: string) => {
                    const newKey: PersonalAPIKeyType = await api.create('api/projects/@current/personal-api-keys/', {
                        label,
                    })
                    return [newKey, ...values.keys]
                },
                deleteKey: async (key: PersonalAPIKeyType) => {
                    await api.delete(`api/projects/@current/personal-api-keys/${key.id}/`)
                    return (values.keys as PersonalAPIKeyType[]).filter((filteredKey) => filteredKey.id != key.id)
                },
            },
        ],
    }),
    listeners: () => ({
        createKeySuccess: ({ keys }: { keys: PersonalAPIKeyType[] }) => {
            copyToClipboard(keys[0].value, 'personal API key value')
        },
        deleteKeySuccess: ({}: { keys: PersonalAPIKeyType[] }) => {
            toast.success(`Personal API key deleted.`)
        },
    }),

    events: ({ actions }) => ({
        afterMount: [actions.loadKeys],
    }),
})

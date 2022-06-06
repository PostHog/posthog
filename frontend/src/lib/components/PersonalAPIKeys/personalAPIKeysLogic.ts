import { kea } from 'kea'
import api from 'lib/api'
import { PersonalAPIKeyType } from '~/types'
import type { personalAPIKeysLogicType } from './personalAPIKeysLogicType'
import { copyToClipboard } from 'lib/utils'
import { lemonToast } from '../lemonToast'

export const personalAPIKeysLogic = kea<personalAPIKeysLogicType>({
    path: ['lib', 'components', 'PersonalAPIKeys', 'personalAPIKeysLogic'],
    loaders: ({ values }) => ({
        keys: [
            [] as PersonalAPIKeyType[],
            {
                loadKeys: async () => {
                    const response: PersonalAPIKeyType[] = await api.get('api/personal_api_keys/')
                    return response
                },
                createKey: async (label: string) => {
                    const newKey: PersonalAPIKeyType = await api.create('api/personal_api_keys/', {
                        label,
                    })
                    return [newKey, ...values.keys]
                },
                deleteKey: async (key: PersonalAPIKeyType) => {
                    await api.delete(`api/personal_api_keys/${key.id}/`)
                    return (values.keys as PersonalAPIKeyType[]).filter((filteredKey) => filteredKey.id != key.id)
                },
            },
        ],
    }),
    listeners: () => ({
        createKeySuccess: ({ keys }: { keys: PersonalAPIKeyType[] }) => {
            keys[0]?.value && copyToClipboard(keys[0].value, 'personal API key value')
        },
        deleteKeySuccess: ({}: { keys: PersonalAPIKeyType[] }) => {
            lemonToast.success(`Personal API key deleted`)
        },
    }),

    events: ({ actions }) => ({
        afterMount: [actions.loadKeys],
    }),
})

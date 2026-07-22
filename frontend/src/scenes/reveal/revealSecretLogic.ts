import { actions, kea, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { urlToAction } from 'kea-router'

import api from 'lib/api'

import type { revealSecretLogicType } from './revealSecretLogicType'

export interface SecretMeta {
    secret_type: string
}

export interface RevealedSecret {
    secret_type: string
    value: string
}

export const revealSecretLogic = kea<revealSecretLogicType>([
    path(['scenes', 'reveal', 'revealSecretLogic']),
    actions({
        setToken: (token: string) => ({ token }),
    }),
    reducers({
        token: ['' as string, { setToken: (_, { token }) => token }],
        // Peek failing means the link is expired, already revealed, or not ours — all "unavailable".
        unavailable: [
            false as boolean,
            {
                loadMetaFailure: () => true,
                loadMetaSuccess: () => false,
                revealFailure: () => true,
            },
        ],
    }),
    loaders(({ values }) => ({
        // Peek: fetch only the type + availability, without consuming the secret.
        secretMeta: [
            null as SecretMeta | null,
            {
                loadMeta: async () => {
                    return await api.get(`api/one_time_secrets/${values.token}/`)
                },
            },
        ],
        // Reveal: the single call that returns the value and burns the link server-side.
        revealedSecret: [
            null as RevealedSecret | null,
            {
                reveal: async () => {
                    return await api.create(`api/one_time_secrets/${values.token}/reveal/`)
                },
            },
        ],
    })),
    urlToAction(({ actions }) => ({
        '/reveal/:token': ({ token }) => {
            if (token) {
                actions.setToken(token)
                actions.loadMeta()
            }
        },
    })),
])

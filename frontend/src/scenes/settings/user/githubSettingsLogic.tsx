import { actions, connect, kea, listeners, path, selectors } from 'kea'
import { urlToAction } from 'kea-router'
import api from 'lib/api'
import { userLogic } from 'scenes/userLogic'

import type { githubSettingsLogicType } from './githubSettingsLogicType'

const GITHUB_APP = 'githog-alpha'

export const githubSettingsLogic = kea<githubSettingsLogicType>(
    /*<githubSettingsLogicType>*/ [
        path(['lib', 'components', 'githubSettingsLogic']),
        connect({
            values: [userLogic, ['user']],
            actions: [userLogic, ['updateUser']],
        }),
        actions({
            completeInstallation: (state: string, installationId: string) => ({ state, installationId }),
        }),
        listeners(({ actions }) => ({
            async completeInstallation({ state, installationId }) {
                // Update the current user's GitHub installation ID
                // sending the state as a header for server verification
                const response = await api.update(
                    'api/users/@me',
                    { github_installation_id: installationId },
                    { headers: { 'X-GitHub-State': state } }
                )
                actions.updateUser(response, undefined, { 'X-GitHub-State': state })
            },
        })),
        selectors({
            installationUrl: [
                () => [],
                () => `https://github.com/apps/${GITHUB_APP}/installations/new?state=someRandomState`,
            ],
            isInstalled: [(s) => [s.user], (user) => user?.github_installation_id !== null],
        }),
        urlToAction(({ actions }) => ({
            '*': (_, searchParams) => {
                const { installation_id, state } = searchParams
                if (installation_id && state) {
                    actions.completeInstallation(state, installation_id)
                }
            },
        })),
    ]
)

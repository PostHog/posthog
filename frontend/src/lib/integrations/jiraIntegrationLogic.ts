import { actions, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { JiraProjectType } from '~/types'

import type { jiraIntegrationLogicType } from './jiraIntegrationLogicType'

export const jiraIntegrationLogic = kea<jiraIntegrationLogicType>([
    props({} as { id: number }),
    key((props) => props.id),
    path((key) => ['lib', 'integrations', 'jiraIntegrationLogic', key]),
    actions({
        loadJiraProjects: () => ({}),
    }),

    loaders(({ props }) => ({
        jiraProjects: [
            [] as JiraProjectType[],
            {
                loadJiraProjects: async () => {
                    const res = await api.integrations.jiraProjects(props.id)
                    return res.projects
                },
            },
        ],
    })),
])

import { afterMount, kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import type { discussionMentionDestinationsLogicType } from './discussionMentionDestinationsLogicType'

export interface DiscussionMentionDestination {
    id: string
    name: string
    type: string
    icon_url?: string | null
}

export interface ProjectWithDestinations {
    id: number
    name: string
    destinations: DiscussionMentionDestination[]
}

interface DiscussionMentionDestinationsResponse {
    projects: ProjectWithDestinations[]
}

export const discussionMentionDestinationsLogic = kea<discussionMentionDestinationsLogicType>([
    path(['scenes', 'settings', 'user', 'discussionMentionDestinationsLogic']),

    loaders({
        projects: [
            [] as ProjectWithDestinations[],
            {
                loadProjects: async () => {
                    const response = await api.get<DiscussionMentionDestinationsResponse>(
                        'api/users/@me/discussion_mention_destinations/'
                    )
                    return response.projects
                },
            },
        ],
    }),

    afterMount(({ actions }) => {
        actions.loadProjects()
    }),
])

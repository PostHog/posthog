import { LemonDialog, LemonInput } from '@posthog/lemon-ui'
import { actions, kea, listeners, path } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { ErrorTrackingTeam } from 'lib/components/Errors/types'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { UserBasicType } from '~/types'

import type { errorTrackingTeamsLogicType } from './errorTrackingTeamsLogicType'

export const errorTrackingTeamsLogic = kea<errorTrackingTeamsLogicType>([
    path(['scenes', 'error-tracking', 'errorTrackingTeamsLogic']),

    actions({
        ensureAllTeamsLoaded: true,
        openTeamCreationForm: true,
    }),

    loaders(({ values }) => ({
        teams: [
            [] as ErrorTrackingTeam[],
            {
                loadTeams: async () => {
                    const response = await api.errorTracking.teams()
                    return response.results
                },
                deleteTeam: async (id: string) => {
                    await api.errorTracking.deleteTeam(id)
                    const newValues = [...values.teams]
                    return newValues.filter((v) => v.id !== id)
                },
                createTeam: async (name: string) => {
                    const response = await api.errorTracking.createTeam(name)
                    return [...values.teams, response]
                },
                addTeamMember: async ({ teamId, user }: { teamId: string; user: UserBasicType }) => {
                    const team = values.teams.find((team) => team.id === teamId)
                    if (team) {
                        await api.errorTracking.addTeamMember(teamId, user.id)
                        team.members = [...team.members, user]
                        return values.teams.map((t) => (t.id === teamId ? team : t))
                    }
                    return values.teams
                },
                removeTeamMember: async ({ teamId, user }: { teamId: string; user: UserBasicType }) => {
                    const team = values.teams.find((team) => team.id === teamId)
                    if (team) {
                        await api.errorTracking.removeTeamMember(teamId, user.id)
                        team.members = team.members.filter((m) => m.id !== user.id)
                        return values.teams.map((t) => (t.id === teamId ? team : t))
                    }
                    return values.teams
                },
            },
        ],
    })),

    listeners(({ values, actions }) => ({
        openTeamCreationForm: () => {
            LemonDialog.openForm({
                title: 'Create team',
                initialValues: { name: '' },
                content: (
                    <LemonField name="name">
                        <LemonInput placeholder="Name" autoFocus />
                    </LemonField>
                ),
                errors: { name: (name) => (!name ? 'You must enter a name' : undefined) },
                onSubmit: ({ name }) => actions.createTeam(name),
            })
        },

        ensureAllTeamsLoaded: () => {
            if (values.teamsLoading) {
                return
            }
            if (values.teams.length === 0) {
                actions.loadTeams()
            }
        },
    })),
])

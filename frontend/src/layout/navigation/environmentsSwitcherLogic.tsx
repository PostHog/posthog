import FuseClass from 'fuse.js'
import { actions, connect, kea, path, reducers, selectors } from 'kea'

import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { ProjectBasicType, TeamBasicType } from '~/types'

import type { environmentSwitcherLogicType } from './environmentsSwitcherLogicType'

// Helping kea-typegen navigate the exported default class for Fuse
export interface Fuse<T> extends FuseClass<T> {}

export type ProjectsMap = Map<
    TeamBasicTypeWithProjectName['project_id'],
    [TeamBasicTypeWithProjectName['project_name'], TeamBasicTypeWithProjectName[]]
>

export interface TeamBasicTypeWithProjectName extends TeamBasicType {
    project_name: string
}

export const environmentSwitcherLogic = kea<environmentSwitcherLogicType>([
    path(['layout', 'navigation', 'environmentsSwitcherLogic']),
    connect(() => ({
        values: [userLogic, ['user'], teamLogic, ['currentTeam'], organizationLogic, ['currentOrganization']],
    })),
    actions({
        setEnvironmentSwitcherSearch: (input: string) => ({ input }),
    }),
    reducers({
        environmentSwitcherSearch: [
            '',
            {
                setEnvironmentSwitcherSearch: (_, { input }) => input,
            },
        ],
    }),
    selectors({
        allTeamsSorted: [
            (s) => [s.currentOrganization, s.currentTeam],
            (currentOrganization, currentTeam): TeamBasicTypeWithProjectName[] => {
                const collection: TeamBasicTypeWithProjectName[] = []
                if (currentOrganization) {
                    const projectIdToName = Object.fromEntries(
                        currentOrganization.projects.map((project) => [project.id, project.name])
                    )
                    for (const team of currentOrganization.teams) {
                        collection.push({
                            ...team,
                            project_name: projectIdToName[team.project_id],
                        })
                    }
                }
                collection.sort((a, b) => {
                    // Sorting logic:
                    // 1. first by whether the team is the current team,
                    // 2. then by whether the project is the current project,
                    // 3. then by project name,
                    // 4. then by team name
                    if (a.id === currentTeam?.id) {
                        return -1
                    } else if (b.id === currentTeam?.id) {
                        return 1
                    }
                    if (a.project_id !== b.project_id) {
                        if (a.project_id === currentTeam?.project_id) {
                            return -1
                        } else if (b.project_id === currentTeam?.project_id) {
                            return 1
                        }
                        return a.project_name.localeCompare(b.project_name)
                    }
                    return a.name.localeCompare(b.name)
                })
                return collection
            },
        ],
        teamsFuse: [
            (s) => [s.allTeamsSorted],
            (allTeamsSorted): Fuse<TeamBasicTypeWithProjectName> => {
                return new FuseClass(allTeamsSorted, { keys: ['name', 'project_name'] })
            },
        ],
        projectsSorted: [
            (s) => [s.currentOrganization, s.currentTeam],
            (currentOrganization, currentTeam): ProjectBasicType[] => {
                // Includes projects that have no environments
                if (!currentOrganization) {
                    return []
                }
                const collection: ProjectBasicType[] = currentOrganization.projects.slice()
                collection.sort((a, b) => {
                    // Sorting logic: 1. first by whether the project is the current project, 2. then by project name
                    if (a.id === currentTeam?.id) {
                        return -1
                    } else if (b.id === currentTeam?.id) {
                        return 1
                    }
                    return a.name.localeCompare(b.name)
                })
                return collection
            },
        ],
        searchedProjectsMap: [
            (s) => [s.projectsSorted, s.allTeamsSorted, s.teamsFuse, s.environmentSwitcherSearch, s.currentTeam],
            (projectsSorted, allTeamsSorted, teamsFuse, environmentSwitcherSearch, currentTeam): ProjectsMap => {
                // Using a map so that insertion order is preserved
                // (JS objects don't preserve the order for keys that are numbers)
                const projectsWithTeamsSorted: ProjectsMap = new Map()

                if (environmentSwitcherSearch) {
                    const matchingTeams = teamsFuse.search(environmentSwitcherSearch).map((result) => result.item)
                    matchingTeams.sort(
                        // We must always have the current project first if it's in the search results - crucial!
                        (a, b) =>
                            (a.project_id === currentTeam?.project_id ? -1 : 0) -
                            (b.project_id === currentTeam?.project_id ? -1 : 0)
                    )
                    for (const team of matchingTeams) {
                        if (!projectsWithTeamsSorted.has(team.project_id)) {
                            projectsWithTeamsSorted.set(team.project_id, [team.project_name, []])
                        }
                        projectsWithTeamsSorted.get(team.project_id)![1].push(team)
                    }
                } else {
                    for (const project of projectsSorted) {
                        projectsWithTeamsSorted.set(project.id, [project.name, []])
                    }
                    for (const team of allTeamsSorted) {
                        projectsWithTeamsSorted.get(team.project_id)![1].push(team)
                    }
                }

                return projectsWithTeamsSorted
            },
        ],
    }),
])

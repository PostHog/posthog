import FuseClass from 'fuse.js'
import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { TeamBasicType } from '~/types'

import type { projectSwitcherLogicType } from './projectSwitcherLogicType'

// Helping kea-typegen navigate the exported default class for Fuse
export interface Fuse<T> extends FuseClass<T> {}

export type ProjectsMap = Map<
    TeamBasicTypeWithProjectName['project_id'],
    [TeamBasicTypeWithProjectName['project_name'], TeamBasicTypeWithProjectName[]]
>

export interface TeamBasicTypeWithProjectName extends TeamBasicType {
    project_name: string
}

export const projectSwitcherLogic = kea<projectSwitcherLogicType>([
    path(['layout', 'navigation', 'projectSwitcherLogic']),
    connect(() => ({
        values: [userLogic, ['user'], teamLogic, ['currentTeam'], organizationLogic, ['currentOrganization']],
    })),
    actions({
        setProjectSwitcherSearch: (input: string) => ({ input }),
    }),
    reducers({
        projectSwitcherSearch: [
            '',
            {
                setProjectSwitcherSearch: (_, { input }) => input,
            },
        ],
    }),
    selectors({
        allTeamsSorted: [
            (s) => [s.currentOrganization, s.currentTeam],
            (currentOrganization, currentTeam): TeamBasicTypeWithProjectName[] => {
                const collection: TeamBasicTypeWithProjectName[] = []
                if (currentOrganization) {
                    const rootTeamIdToName = Object.fromEntries(
                        currentOrganization.teams.map((t) => [t.root_team_id, t.name])
                    )
                    for (const team of currentOrganization.teams) {
                        collection.push({
                            ...team,
                            project_name: rootTeamIdToName[team.root_team_id],
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
                    if (a.root_team_id !== b.root_team_id) {
                        if (a.root_team_id === currentTeam?.root_team_id) {
                            return -1
                        } else if (b.root_team_id === currentTeam?.root_team_id) {
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
            (currentOrganization, currentTeam): TeamBasicType[] => {
                // Includes projects that have no environments
                if (!currentOrganization) {
                    return []
                }
                const collection: TeamBasicType[] = currentOrganization.teams.filter(
                    (team) => team.id === team.root_team_id
                )
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
            (s) => [s.projectsSorted, s.allTeamsSorted, s.teamsFuse, s.projectSwitcherSearch, s.currentTeam],
            (projectsSorted, allTeamsSorted, teamsFuse, projectSwitcherSearch, currentTeam): ProjectsMap => {
                // Using a map so that insertion order is preserved
                // (JS objects don't preserve the order for keys that are numbers)
                const projectsWithTeamsSorted: ProjectsMap = new Map()

                if (projectSwitcherSearch) {
                    const matchingTeams = teamsFuse.search(projectSwitcherSearch).map((result) => result.item)
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
                        projectsWithTeamsSorted.get(team.root_team_id)![1].push(team)
                    }
                }

                return projectsWithTeamsSorted
            },
        ],
    }),
])

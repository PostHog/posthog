import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { DashboardsTab } from 'scenes/dashboard/dashboards/dashboardsLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import type { DashboardTemplateType } from '~/types'

import type { dashboardTemplateCopyLogicType } from './dashboardTemplateCopyLogicType'
import { dashboardTemplatesLogic } from './dashboardTemplatesLogic'

export interface DashboardTemplateCopyLogicProps {
    sourceTemplateId: string
    sourceTeamId?: number
}

function maybeReplaceUrlWithSourceTeam(props: DashboardTemplateCopyLogicProps, currentTeamId: number | null): void {
    if (props.sourceTeamId !== undefined) {
        return
    }
    if (currentTeamId == null || !props.sourceTemplateId) {
        return
    }
    router.actions.replace(urls.dashboardTemplateCopyToProject(props.sourceTemplateId, currentTeamId))
}

export const dashboardTemplateCopyLogic = kea<dashboardTemplateCopyLogicType>([
    path(['scenes', 'dashboard', 'dashboards', 'templates', 'dashboardTemplateCopyLogic']),
    props({} as DashboardTemplateCopyLogicProps),
    key((props) => props.sourceTemplateId),
    connect(() => ({
        values: [organizationLogic, ['currentOrganization'], teamLogic, ['currentTeamId']],
    })),
    actions({
        setDestinationTeamId: (teamId: number | null) => ({ teamId }),
    }),
    reducers({
        destinationTeamId: [
            null as number | null,
            {
                setDestinationTeamId: (_, { teamId }) => teamId,
            },
        ],
        sourceTemplateLoadFailed: [
            false,
            {
                loadSourceTemplate: () => false,
                loadSourceTemplateSuccess: () => false,
                loadSourceTemplateFailure: () => true,
            },
        ],
    }),
    loaders(({ values, props }) => ({
        sourceTemplate: [
            null as DashboardTemplateType | null,
            {
                loadSourceTemplate: async () => {
                    const sourceTeamId = props.sourceTeamId ?? values.currentTeamId
                    if (sourceTeamId == null) {
                        throw new Error('Missing source project for this template.')
                    }
                    return await api.dashboardTemplates.get(props.sourceTemplateId, sourceTeamId)
                },
            },
        ],
        copyResult: [
            null as DashboardTemplateType | null,
            {
                submitCopy: async () => {
                    const { destinationTeamId } = values
                    if (!destinationTeamId) {
                        lemonToast.error('Select a destination project')
                        throw new Error('Select a destination project')
                    }
                    return await api.dashboardTemplates.copyBetweenProjects(destinationTeamId, props.sourceTemplateId)
                },
            },
        ],
    })),
    selectors({
        teamOptions: [
            (s) => [s.currentOrganization, s.currentTeamId],
            (currentOrganization, currentTeamId) =>
                (currentOrganization?.teams ?? [])
                    .filter((team) => team.id !== currentTeamId)
                    .sort((a, b) => a.name.localeCompare(b.name))
                    .map((team) => ({ value: team.id, label: team.name })),
        ],
    }),
    subscriptions(({ props }) => ({
        currentTeamId: (currentTeamId) => {
            maybeReplaceUrlWithSourceTeam(props, currentTeamId)
        },
    })),
    listeners(({ values }) => ({
        submitCopySuccess: () => {
            const destinationTeamId = values.destinationTeamId
            const destTeam = values.currentOrganization?.teams.find((t) => t.id === destinationTeamId)
            const destName = destTeam?.name || 'the selected project'
            lemonToast.success(
                `Copied to ${destName}`,
                destinationTeamId != null
                    ? {
                          button: {
                              label: 'Open project',
                              action: () => {
                                  window.location.href = urls.project(destinationTeamId, urls.dashboards())
                              },
                          },
                      }
                    : {}
            )
            dashboardTemplatesLogic.findMounted({ scope: 'default', templatesTabList: true })?.actions.getAllTemplates()
            router.actions.push(urls.dashboards(), { tab: DashboardsTab.Templates })
        },
    })),
    afterMount(({ actions, props, values }) => {
        maybeReplaceUrlWithSourceTeam(props, values.currentTeamId)
        actions.loadSourceTemplate()
    }),
])

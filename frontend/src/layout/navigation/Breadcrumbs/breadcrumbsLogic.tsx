import { kea } from 'kea'
import { organizationLogic } from '../../../scenes/organizationLogic'
import { teamLogic } from '../../../scenes/teamLogic'
import './Breadcrumbs.scss'
import { breadcrumbsLogicType } from './breadcrumbsLogicType'
import { sceneLogic } from '../../../scenes/sceneLogic'
import { Scene } from '../../../scenes/sceneTypes'
import { urls } from '../../../scenes/urls'
import { preflightLogic } from '../../../scenes/PreflightCheck/logic'
import { identifierToHuman, stripHTTP } from '../../../lib/utils'
import { userLogic } from '../../../scenes/userLogic'
import React from 'react'
import { Lettermark } from '../../../lib/components/Lettermark/Lettermark'
import { ProfilePicture } from '../../../lib/components/ProfilePicture'
import { dashboardsModel } from '../../../models/dashboardsModel'
import { featureFlagLogic } from '../../../scenes/feature-flags/featureFlagLogic'
import { personsLogic } from '../../../scenes/persons/personsLogic'
import { asDisplay } from '../../../scenes/persons/PersonHeader'
import { PopupProps } from 'lib/components/Popup/Popup'
import { ProjectSwitcherOverlay } from '~/layout/navigation/ProjectSwitcher'
import { OrganizationSwitcherOverlay } from '~/layout/navigation/OrganizationSwitcher'

export interface Breadcrumb {
    /** Name to display. */
    name: string | null | undefined
    /** Symbol, e.g. a lettermark or a profile picture. */
    symbol?: React.ReactNode
    /** Path to link to. */
    path?: string
    /** Whether this breadcrumb refers to the current location. */
    here?: boolean
    /** Whether to show a custom popup */
    popup?: Pick<PopupProps, 'overlay' | 'sameWidth' | 'actionable'>
}

export const breadcrumbsLogic = kea<breadcrumbsLogicType<Breadcrumb>>({
    path: ['layout', 'navigation', 'Breadcrumbs', 'breadcrumbsLogic'],
    props: {} as {
        hashParams: Record<string, any>
    },
    connect: {
        values: [
            preflightLogic,
            ['preflight'],
            sceneLogic,
            ['sceneConfig', 'activeScene'],
            userLogic,
            ['user', 'otherOrganizations'],
            organizationLogic,
            ['currentOrganization'],
            teamLogic,
            ['currentTeam'],
            dashboardsModel,
            ['rawDashboards', 'lastDashboardId'],
            featureFlagLogic,
            ['featureFlag'],
            personsLogic,
            ['person'],
        ],
    },
    selectors: () => ({
        breadcrumbs: [
            (s) => [
                s.preflight,
                s.sceneConfig,
                s.activeScene,
                s.user,
                s.currentOrganization,
                s.currentTeam,
                s.rawDashboards,
                s.lastDashboardId,
                s.featureFlag,
                s.person,
                s.otherOrganizations,
            ],
            (
                preflight,
                sceneConfig,
                activeScene,
                user,
                currentOrganization,
                currentTeam,
                rawDashboards,
                lastDashboardId,
                featureFlag,
                person,
                otherOrganizations
            ) => {
                const breadcrumbs: Breadcrumb[] = []
                if (!activeScene || !sceneConfig) {
                    return breadcrumbs
                }
                // User
                if (sceneConfig.personal) {
                    if (!user) {
                        return breadcrumbs
                    }
                    breadcrumbs.push({
                        name: user.first_name,
                        symbol: <ProfilePicture name={user.first_name} email={user.email} size="md" />,
                    })
                }
                // Instance
                if (sceneConfig.instanceLevel) {
                    if (!preflight?.site_url) {
                        return breadcrumbs
                    }
                    breadcrumbs.push({
                        name: stripHTTP(preflight.site_url),
                        symbol: <Lettermark name="@" />,
                    })
                }
                // Organization
                if (sceneConfig.organizationBased || sceneConfig.projectBased) {
                    if (!currentOrganization) {
                        return breadcrumbs
                    }
                    breadcrumbs.push({
                        name: currentOrganization.name,
                        symbol: <Lettermark name={currentOrganization.name} />,
                        popup:
                            otherOrganizations?.length || preflight?.can_create_org
                                ? {
                                      overlay: <OrganizationSwitcherOverlay />,
                                      actionable: true,
                                  }
                                : undefined,
                    })
                }
                // Project
                if (sceneConfig.projectBased) {
                    if (!currentTeam) {
                        return breadcrumbs
                    }
                    breadcrumbs.push({
                        name: currentTeam.name,
                        popup: {
                            overlay: <ProjectSwitcherOverlay />,
                            actionable: true,
                        },
                    })
                }
                // Parent page handling
                switch (activeScene) {
                    case Scene.Person:
                        breadcrumbs.push({
                            name: 'Persons',
                            path: urls.persons(),
                        })
                        // Current place
                        breadcrumbs.push({
                            name: person ? asDisplay(person) : null,
                            here: true,
                        })
                        break
                    case Scene.Insights:
                        breadcrumbs.push({
                            name: 'Insights',
                            path: urls.savedInsights(),
                        })
                        // Current place
                        breadcrumbs.push({
                            name: 'Insight',
                            here: true,
                        })
                        break
                    case Scene.Action:
                        breadcrumbs.push({
                            name: 'Actions',
                            path: urls.actions(),
                        })
                        // Current place
                        breadcrumbs.push({
                            name: 'Action',
                            here: true,
                        })
                        break
                    case Scene.FeatureFlag:
                        breadcrumbs.push({
                            name: 'Feature flags',
                            path: urls.featureFlags(),
                        })
                        // Current place
                        breadcrumbs.push({
                            name: featureFlag ? featureFlag.key || 'Unnamed flag' : null,
                            here: true,
                        })
                        break
                    case Scene.Dashboard:
                        breadcrumbs.push({
                            name: 'Dashboards',
                            path: urls.dashboards(),
                        })
                        // Current place
                        breadcrumbs.push({
                            name:
                                lastDashboardId !== null && lastDashboardId in rawDashboards
                                    ? rawDashboards[lastDashboardId].name || 'Unnamed dashboard'
                                    : null,
                            here: true,
                        })
                        break
                    default:
                        // Current place
                        breadcrumbs.push({
                            name: sceneConfig.name || identifierToHuman(activeScene),
                            here: true,
                        })
                }
                return breadcrumbs
            },
        ],
    }),
})

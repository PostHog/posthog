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

export interface Breadcrumb {
    /** Name to display. */
    name: string | null | undefined
    /** Symbol, e.g. a lettermark or a profile picture. */
    symbol?: React.ReactNode
    /** Path to link to. */
    path?: string
    /** Tooltip on hover. */
    tooltip?: string
    /** Whether this breadcrumb refers to the current location. */
    here?: boolean
}

export const breadcrumbsLogic = kea<breadcrumbsLogicType<Breadcrumb>>({
    props: {} as {
        hashParams: Record<string, any>
    },
    connect: {
        values: [
            preflightLogic,
            ['preflight', 'preflightLoading'],
            sceneLogic,
            ['sceneConfig', 'activeScene'],
            userLogic,
            ['user', 'userLoading'],
            organizationLogic,
            ['currentOrganization', 'currentOrganizationLoading'],
            teamLogic,
            ['currentTeam', 'currentTeamLoading'],
            teamLogic,
            ['currentTeam', 'currentTeamLoading'],
            dashboardsModel,
            ['rawDashboards', 'lastDashboardId'],
            featureFlagLogic,
            ['featureFlag'],
            personsLogic,
            ['person'],
        ],
    },
    selectors: {
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
                person
            ) => {
                const breadcrumbs: Breadcrumb[] = []
                if (!activeScene) {
                    return breadcrumbs
                }
                // User
                if (sceneConfig?.personal) {
                    if (!user) {
                        return breadcrumbs
                    }
                    breadcrumbs.push({
                        name: user.first_name,
                        tooltip: 'You',
                        symbol: <ProfilePicture name={user.first_name} email={user.email} size="md" />,
                    })
                }
                // Instance
                if (sceneConfig?.instanceLevel) {
                    if (!preflight?.site_url) {
                        return breadcrumbs
                    }
                    breadcrumbs.push({
                        name: stripHTTP(preflight.site_url),
                        tooltip: 'This PostHog instance',
                        symbol: <Lettermark name="@" />,
                    })
                }
                // Organization
                if (sceneConfig?.organizationBased || sceneConfig?.projectBased) {
                    if (!currentOrganization) {
                        return breadcrumbs
                    }
                    breadcrumbs.push({
                        name: currentOrganization.name,
                        symbol: <Lettermark name={currentOrganization.name} />,
                        tooltip: 'Current organization',
                    })
                }
                // Project
                if (sceneConfig?.projectBased) {
                    if (!currentTeam) {
                        return breadcrumbs
                    }
                    breadcrumbs.push({
                        name: currentTeam.name,
                        tooltip: 'Current project',
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
                            name: identifierToHuman(activeScene),
                            here: true,
                        })
                }
                return breadcrumbs
            },
        ],
        breadcrumbsLoading: [
            (s) => [
                s.preflightLoading,
                s.sceneConfig,
                s.userLoading,
                s.currentOrganizationLoading,
                s.currentTeamLoading,
            ],
            (preflightLoading, sceneConfig, userLoading, currentOrganizationLoading, currentTeamLoading) => {
                if (!sceneConfig) {
                    return true
                }
                // User
                if (sceneConfig.personal && userLoading) {
                    return true
                }
                // Instance
                if (sceneConfig.instanceLevel && preflightLoading) {
                    return true
                }
                // Organization
                if ((sceneConfig.organizationBased || sceneConfig.projectBased) && currentOrganizationLoading) {
                    return true
                }
                // Project
                if (sceneConfig.projectBased && currentTeamLoading) {
                    return true
                }
                return false
            },
        ],
    },
})

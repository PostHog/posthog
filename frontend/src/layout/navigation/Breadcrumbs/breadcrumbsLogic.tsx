import { kea } from 'kea'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'
import './Breadcrumbs.scss'
import { breadcrumbsLogicType } from './breadcrumbsLogicType'
import { sceneLogic } from 'scenes/sceneLogic'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { identifierToHuman, stripHTTP } from 'lib/utils'
import { userLogic } from 'scenes/userLogic'
import React from 'react'
import { Lettermark } from 'lib/components/Lettermark/Lettermark'
import { ProfilePicture } from 'lib/components/ProfilePicture'
import { ProjectSwitcherOverlay } from '~/layout/navigation/ProjectSwitcher'
import { OrganizationSwitcherOverlay } from '~/layout/navigation/OrganizationSwitcher'
import { Breadcrumb } from '~/types'

export const breadcrumbsLogic = kea<breadcrumbsLogicType>({
    path: ['layout', 'navigation', 'Breadcrumbs', 'breadcrumbsLogic'],
    props: {} as {
        hashParams: Record<string, any>
    },
    connect: () => ({
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
        ],
    }),
    selectors: () => ({
        sceneBreadcrumbs: [
            () => [
                // We're effectively passing the selector through to the scene logic, and "recalculating"
                // this every time it's rendered. Caching will happen within the scene's breadcrumb selector.
                (state, props) => {
                    const activeSceneLogic = sceneLogic.selectors.activeSceneLogic(state, props)
                    if (activeSceneLogic && 'breadcrumbs' in activeSceneLogic.selectors) {
                        const activeLoadedScene = sceneLogic.selectors.activeLoadedScene(state, props)
                        return activeSceneLogic.selectors.breadcrumbs(
                            state,
                            activeLoadedScene?.sceneParams?.params || props
                        )
                    } else {
                        return []
                    }
                },
            ],
            (crumbs): Breadcrumb[] => crumbs,
        ],
        breadcrumbs: [
            (s) => [
                s.preflight,
                s.sceneConfig,
                s.activeScene,
                s.user,
                s.currentOrganization,
                s.currentTeam,
                s.otherOrganizations,
                s.sceneBreadcrumbs,
            ],
            (
                preflight,
                sceneConfig,
                activeScene,
                user,
                currentOrganization,
                currentTeam,
                otherOrganizations,
                sceneBreadcrumbs
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

                if (sceneBreadcrumbs && sceneBreadcrumbs.length > 0) {
                    return [...breadcrumbs, ...sceneBreadcrumbs]
                }

                // Current place
                breadcrumbs.push({
                    name: sceneConfig.name || identifierToHuman(activeScene),
                })
                return breadcrumbs
            },
        ],
    }),
})

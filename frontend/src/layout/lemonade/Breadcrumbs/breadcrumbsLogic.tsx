import { kea } from 'kea'
import { organizationLogic } from '../../../scenes/organizationLogic'
import { teamLogic } from '../../../scenes/teamLogic'
import './Breadcrumbs.scss'
import { breadcrumbsLogicType } from './breadcrumbsLogicType'
import { sceneLogic } from '../../../scenes/sceneLogic'
import { Scene } from '../../../scenes/sceneTypes'
import { urls } from '../../../scenes/urls'
import { preflightLogic } from '../../../scenes/PreflightCheck/logic'
import { stripHTTP } from '../../../lib/utils'
import { userLogic } from '../../../scenes/userLogic'
import React from 'react'
import { Lettermark } from '../../../lib/components/Lettermark/Lettermark'
import { ProfilePicture } from '../../../lib/components/ProfilePicture'

export interface Breadcrumb {
    name: string
    symbol?: React.ReactNode
    path?: string
    tooltip?: string
}

export const breadcrumbsLogic = kea<breadcrumbsLogicType<Breadcrumb>>({
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
            ['user'],
            organizationLogic,
            ['currentOrganization'],
            teamLogic,
            ['currentTeam'],
        ],
    }),
    selectors: () => ({
        breadcrumbs: [
            (s) => [s.preflight, s.sceneConfig, s.activeScene, s.user, s.currentOrganization, s.currentTeam],
            (preflight, sceneConfig, activeScene, user, currentOrganization, currentTeam) => {
                const breadcrumbs: Breadcrumb[] = []
                if (sceneConfig.personal) {
                    if (!user) {
                        return breadcrumbs
                    }
                    breadcrumbs.push({
                        name: user.first_name,
                        tooltip: 'You',
                        symbol: <ProfilePicture name={user.first_name} email={user.email} size="md" />,
                    })
                    return breadcrumbs
                }
                if (sceneConfig.instanceLevel) {
                    if (!preflight?.site_url) {
                        return breadcrumbs
                    }
                    breadcrumbs.push({
                        name: stripHTTP(preflight.site_url),
                        tooltip: 'This PostHog instance',
                        symbol: <Lettermark name="@" />,
                    })
                    return breadcrumbs
                }
                if (sceneConfig.organizationBased || sceneConfig.projectBased) {
                    if (!currentOrganization) {
                        return breadcrumbs
                    }
                    breadcrumbs.push({
                        name: currentOrganization.name,
                        symbol: <Lettermark name={currentOrganization.name} />,
                        tooltip: 'Current organization',
                    })
                }
                if (sceneConfig.projectBased) {
                    if (!currentTeam) {
                        return breadcrumbs
                    }
                    breadcrumbs.push({
                        name: currentTeam.name,
                        tooltip: 'Current project',
                    })
                }
                switch (activeScene) {
                    case Scene.Person:
                        breadcrumbs.push({
                            name: 'Persons',
                            path: urls.persons(),
                        })
                        break
                    case Scene.Insights:
                        breadcrumbs.push({
                            name: 'Insights',
                            path: urls.savedInsights(),
                        })
                        break
                    case Scene.FeatureFlag:
                        breadcrumbs.push({
                            name: 'Feature flags',
                            path: urls.featureFlags(),
                        })
                        break
                    case Scene.Dashboard:
                        breadcrumbs.push({
                            name: 'Dashboards',
                            path: urls.dashboards(),
                        })
                        break
                }
                return breadcrumbs
            },
        ],
    }),
})

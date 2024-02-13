import { actions, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'
import { Lettermark } from 'lib/lemon-ui/Lettermark'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { identifierToHuman, objectsEqual, stripHTTP } from 'lib/utils'
import { organizationLogic } from 'scenes/organizationLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { OrganizationSwitcherOverlay } from '~/layout/navigation/OrganizationSwitcher'
import { ProjectSwitcherOverlay } from '~/layout/navigation/ProjectSwitcher'
import { Breadcrumb } from '~/types'

import type { breadcrumbsLogicType } from './breadcrumbsLogicType'

export const breadcrumbsLogic = kea<breadcrumbsLogicType>([
    path(['layout', 'navigation', 'Breadcrumbs', 'breadcrumbsLogic']),
    props(
        {} as {
            hashParams: Record<string, any>
        }
    ),
    connect(() => ({
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
    })),
    actions({
        setActionsContainer: (element: HTMLElement | null) => ({ element }),
        tentativelyRename: (breadcrumbGlobalKey: string, tentativeName: string) => ({
            breadcrumbGlobalKey,
            tentativeName,
        }),
        finishRenaming: true,
    }),
    reducers({
        actionsContainer: [
            null as HTMLElement | null,
            {
                setActionsContainer: (_, { element }) => element,
            },
        ],
        renameState: [
            null as [breadcrumbGlobalKey: string, tentativeName: string] | null,
            {
                tentativelyRename: (_, { breadcrumbGlobalKey, tentativeName }) => [breadcrumbGlobalKey, tentativeName],
                finishRenaming: () => null,
            },
        ],
    }),
    listeners(({ actions }) => ({
        [sceneLogic.actionTypes.loadScene]: () => actions.finishRenaming(), // Cancel renaming on navigation away
    })),
    selectors(() => ({
        sceneBreadcrumbs: [
            (s) => [
                // We're effectively passing the selector through to the scene logic, and "recalculating"
                // this every time it's rendered. Caching will happen within the scene's breadcrumb selector.
                (state, props): Breadcrumb[] => {
                    const activeSceneLogic = sceneLogic.selectors.activeSceneLogic(state, props)
                    const activeScene = s.activeScene(state, props)
                    if (activeSceneLogic && 'breadcrumbs' in activeSceneLogic.selectors) {
                        const activeLoadedScene = sceneLogic.selectors.activeLoadedScene(state, props)
                        return activeSceneLogic.selectors.breadcrumbs(
                            state,
                            activeLoadedScene?.paramsToProps?.(activeLoadedScene?.sceneParams) || props
                        )
                    } else if (activeScene) {
                        const sceneConfig = s.sceneConfig(state, props)
                        return [{ name: sceneConfig?.name ?? identifierToHuman(activeScene), key: activeScene }]
                    } else {
                        return []
                    }
                },
            ],
            (crumbs): Breadcrumb[] => crumbs,
            { equalityCheck: objectsEqual },
        ],
        appBreadcrumbs: [
            (s) => [
                s.preflight,
                s.sceneConfig,
                s.activeScene,
                s.user,
                s.currentOrganization,
                s.currentTeam,
                s.otherOrganizations,
            ],
            (preflight, sceneConfig, activeScene, user, currentOrganization, currentTeam, otherOrganizations) => {
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
                        key: 'me',
                        name: user.first_name,
                        symbol: <ProfilePicture user={user} size="md" />,
                    })
                }
                // Instance
                if (sceneConfig.instanceLevel) {
                    if (!preflight?.site_url) {
                        return breadcrumbs
                    }
                    breadcrumbs.push({
                        key: 'instance',
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
                        key: 'organization',
                        name: currentOrganization.name,
                        symbol: <Lettermark name={currentOrganization.name} />,
                        popover:
                            otherOrganizations?.length || preflight?.can_create_org
                                ? {
                                      overlay: <OrganizationSwitcherOverlay />,
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
                        key: 'project',
                        name: currentTeam.name,
                        popover: {
                            overlay: <ProjectSwitcherOverlay />,
                        },
                    })
                }

                return breadcrumbs
            },
        ],
        sceneBreadcrumbKeys: [
            (s) => [s.sceneBreadcrumbs],
            (sceneBreadcrumbs): Breadcrumb['key'][] => sceneBreadcrumbs.map((breadcrumb) => breadcrumb.key),
        ],
        breadcrumbs: [
            (s) => [s.appBreadcrumbs, s.sceneBreadcrumbs],
            (appBreadcrumbs, sceneBreadcrumbs): Breadcrumb[] => {
                return appBreadcrumbs.concat(sceneBreadcrumbs)
            },
        ],
        firstBreadcrumb: [(s) => [s.breadcrumbs], (breadcrumbs) => breadcrumbs[0]],
        tailBreadcrumbs: [
            (s) => [s.breadcrumbs],
            (breadcrumbs) => {
                const tailBreadcrumbs = breadcrumbs.slice(1)
                // Remove "path" from the last breadcrumb to disable its link
                if (tailBreadcrumbs.length > 0) {
                    delete tailBreadcrumbs[tailBreadcrumbs.length - 1].path
                }
                return tailBreadcrumbs
            },
        ],
        documentTitle: [
            (s) => [s.sceneBreadcrumbs, s.preflight],
            (sceneBreadcrumbs, preflight): string =>
                [
                    ...sceneBreadcrumbs
                        .filter((breadcrumb) => !!breadcrumb.name)
                        .map((breadcrumb) => breadcrumb.name as string)
                        .reverse(),
                    preflight?.demo ? 'PostHog Demo' : 'PostHog',
                ].join(' • '),
        ],
    })),
    subscriptions({
        documentTitle: (documentTitle: string) => {
            if (typeof document !== 'undefined') {
                document.title = documentTitle
            }
        },
    }),
])

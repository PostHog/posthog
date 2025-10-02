import { actions, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { identifierToHuman, objectsEqual, stripHTTP } from 'lib/utils'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { projectLogic } from 'scenes/projectLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { Breadcrumb, ProjectTreeRef } from '~/types'

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
            ['sceneConfig', 'activeSceneId', 'activeTabId'],
            userLogic,
            ['user', 'otherOrganizations'],
            organizationLogic,
            ['currentOrganization'],
            projectLogic,
            ['currentProject'],
            teamLogic,
            ['currentTeam'],
            featureFlagLogic,
            ['featureFlags'],
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
    listeners(({ actions, values }) => ({
        [sceneLogic.actionTypes.loadScene]: () => {
            if (values.renameState) {
                actions.finishRenaming() // Cancel renaming on navigation away
            }
        },
    })),
    selectors(() => ({
        sceneBreadcrumbs: [
            (s) => [
                // We're effectively passing the selector through to the scene logic, and "recalculating"
                // this every time it's rendered. Caching will happen within the scene's breadcrumb selector.
                (state, props): Breadcrumb[] => {
                    const activeSceneLogic = sceneLogic.selectors.activeSceneLogic(state, props)
                    const activeSceneId = s.activeSceneId(state, props)
                    const activeTabId = s.activeTabId(state, props)

                    if (activeSceneLogic && 'breadcrumbs' in activeSceneLogic.selectors) {
                        try {
                            const activeLoadedScene = sceneLogic.selectors.activeLoadedScene(state, props)
                            return activeSceneLogic.selectors.breadcrumbs(state, {
                                ...(activeLoadedScene?.paramsToProps?.(activeLoadedScene?.sceneParams) || props),
                                tabId: activeTabId,
                            })
                        } catch {
                            // If the breadcrumb selector fails, we'll just ignore it and return an empty array below
                        }
                    }

                    if (activeSceneId) {
                        const sceneConfig = s.sceneConfig(state, props)
                        return [{ name: sceneConfig?.name ?? identifierToHuman(activeSceneId), key: activeSceneId }]
                    }
                    return []
                },
            ],
            (crumbs): Breadcrumb[] => crumbs,
            { equalityCheck: objectsEqual },
        ],
        projectTreeRef: [
            (s) => [
                // Similar logic to the breadcrumbs above. This is used to find the object in the project tree.
                (state, props): ProjectTreeRef | null => {
                    const activeSceneLogic = sceneLogic.selectors.activeSceneLogic(state, props)
                    const activeTabId = s.activeTabId(state, props)
                    if (activeSceneLogic && 'projectTreeRef' in activeSceneLogic.selectors) {
                        try {
                            const activeLoadedScene = sceneLogic.selectors.activeLoadedScene(state, props)
                            return activeSceneLogic.selectors.projectTreeRef(state, {
                                ...(activeLoadedScene?.paramsToProps?.(activeLoadedScene?.sceneParams) || props),
                                tabId: activeTabId,
                            })
                        } catch {
                            // If the breadcrumb selector fails, we'll just ignore it and return null below
                        }
                    }
                    return null
                },
            ],
            (ref: ProjectTreeRef | null): ProjectTreeRef | null => ref,
            { equalityCheck: objectsEqual },
        ],
        appBreadcrumbs: [
            (s) => [
                s.preflight,
                s.sceneConfig,
                s.activeSceneId,
                s.user,
                s.currentProject,
                s.currentTeam,
                s.featureFlags,
            ],
            (preflight, sceneConfig, activeSceneId, user, currentProject, currentTeam, featureFlags) => {
                const breadcrumbs: Breadcrumb[] = []
                if (!activeSceneId || !sceneConfig) {
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
                    })
                }
                // Project
                if (sceneConfig.projectBased) {
                    if (!currentProject || !currentTeam) {
                        return breadcrumbs
                    }
                    breadcrumbs.push({
                        key: 'project',
                        name: featureFlags[FEATURE_FLAGS.ENVIRONMENTS] ? currentProject.name : currentTeam.name,
                        tag: featureFlags[FEATURE_FLAGS.ENVIRONMENTS] ? currentTeam.name : null,
                        isPopoverProject: true,
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
        sceneBreadcrumbsDisplayString: [
            (s) => [s.sceneBreadcrumbs],
            (sceneBreadcrumbs): string =>
                sceneBreadcrumbs
                    .filter((breadcrumb) => !!breadcrumb.name)
                    .map((breadcrumb) => breadcrumb.name)
                    .join(' / '),
        ],
        documentTitle: [
            (s) => [s.sceneBreadcrumbs, s.preflight],
            (sceneBreadcrumbs, preflight): string =>
                [
                    ...sceneBreadcrumbs
                        .filter((breadcrumb) => !!breadcrumb.name)
                        .map((breadcrumb) => breadcrumb.name)
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

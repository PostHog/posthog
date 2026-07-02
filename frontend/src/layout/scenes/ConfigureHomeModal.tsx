import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect, useState } from 'react'

import { LemonSegmentedButton, LemonSelect, LemonSelectOptions, LemonTag } from '@posthog/lemon-ui'

import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { dashboardsModel } from '~/models/dashboardsModel'
import { FileSystemIconType } from '~/queries/schema/schema-general'
import { sceneLogic } from '~/scenes/sceneLogic'
import { emptySceneParams } from '~/scenes/scenes'
import { Scene, SceneTab } from '~/scenes/sceneTypes'
import { teamLogic } from '~/scenes/teamLogic'
import { urls } from '~/scenes/urls'

export interface ConfigureHomeModalProps {
    isOpen: boolean
    onClose: () => void
}

export function ConfigureHomeModal({ isOpen, onClose }: ConfigureHomeModalProps): JSX.Element {
    const { homepage } = useValues(sceneLogic)
    const { currentTeam } = useValues(teamLogic)
    const { nameSortedDashboards, dashboardsLoading } = useValues(dashboardsModel)
    const { setHomepage } = useActions(sceneLogic)
    const { updateCurrentTeam } = useActions(teamLogic)

    const isUsingProjectDefault = !homepage
    const isUsingNewTabHomepage = homepage?.sceneId === Scene.NewTab
    const isUsingDefaultDashboard =
        homepage?.sceneId === Scene.Dashboard && homepage?.id?.startsWith('homepage-dashboard-')

    // Local UI selection so users can preview the "Default dashboard" picker even
    // when no `primary_dashboard` is set yet — otherwise the picker is hidden behind
    // a disabled tile, and the only place to set it is the same hidden picker.
    const [pendingMode, setPendingMode] = useState<'launchpad' | 'search' | 'default_dashboard' | null>(null)
    const currentMode = isUsingProjectDefault
        ? 'launchpad'
        : isUsingNewTabHomepage
          ? 'search'
          : isUsingDefaultDashboard
            ? 'default_dashboard'
            : null
    useEffect(() => setPendingMode(null), [currentMode])
    const activeMode = pendingMode ?? currentMode
    const showDashboardPicker = activeMode === 'default_dashboard'

    const projectDefaultDashboardId = currentTeam?.primary_dashboard ?? null

    const homepageDisplayTitle = homepage ? homepage.customTitle || homepage.title : 'Launchpad'
    const homepageSubtitle = isUsingProjectDefault ? 'Default' : isUsingNewTabHomepage ? 'Search' : null

    const projectDefaultDashboardOptions: LemonSelectOptions<number | null> = [
        { value: null, label: 'No default dashboard / show the "new tab" page' },
        ...nameSortedDashboards.map((dashboard) => ({
            value: dashboard.id,
            label: dashboard.name || 'Untitled',
        })),
    ]

    const homepageIcon = homepage?.iconType
    const homepageIconElement = iconForType(
        homepageIcon && homepageIcon !== 'loading' && homepageIcon !== 'blank'
            ? (homepageIcon as FileSystemIconType)
            : isUsingNewTabHomepage
              ? ('default_icon_type' as FileSystemIconType)
              : ('home' as FileSystemIconType)
    )

    const newTabHomepage: SceneTab = {
        id: 'homepage-new-tab',
        pathname: urls.newTab(),
        search: '',
        hash: '',
        title: 'Search',
        iconType: 'search',
        sceneId: Scene.NewTab,
        sceneKey: 'newTab',
        sceneParams: emptySceneParams,
    }

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            title="Configure homepage"
            description="Choose your personal homepage for this project."
            width="48rem"
        >
            <section className="flex flex-col gap-3">
                <div className="flex flex-col gap-2">
                    <div className="flex items-center justify-between gap-3 rounded-lg border border-border px-3 py-2 bg-surface-primary">
                        <div className="flex min-w-0 items-center gap-2">
                            <span className="shrink-0 text-lg text-muted-alt">{homepageIconElement}</span>
                            <div className="min-w-0">
                                <div className="truncate font-medium text-primary">{homepageDisplayTitle}</div>
                                {homepageSubtitle && (
                                    <div className="truncate text-xs text-muted">{homepageSubtitle}</div>
                                )}
                            </div>
                        </div>
                        <LemonSegmentedButton
                            size="small"
                            value={activeMode ?? undefined}
                            onChange={(newValue) => {
                                posthog.capture('homepage configure set homepage', {
                                    'homepage choice': newValue,
                                })
                                if (newValue === 'launchpad') {
                                    setPendingMode(null)
                                    setHomepage(null)
                                } else if (newValue === 'search') {
                                    setPendingMode(null)
                                    setHomepage(newTabHomepage)
                                } else if (newValue === 'default_dashboard') {
                                    const dashboardId = currentTeam?.primary_dashboard
                                    if (dashboardId) {
                                        setPendingMode(null)
                                        setHomepage({
                                            id: `homepage-dashboard-${dashboardId}`,
                                            pathname: urls.dashboard(dashboardId),
                                            search: '',
                                            hash: '',
                                            title: 'Default dashboard',
                                            iconType: 'dashboard',
                                            sceneId: Scene.Dashboard,
                                            sceneKey: `dashboard-${dashboardId}`,
                                            sceneParams: emptySceneParams,
                                        })
                                    } else {
                                        // No primary dashboard yet — keep selection local so the picker
                                        // appears; setHomepage fires once a dashboard is chosen below.
                                        setPendingMode('default_dashboard')
                                    }
                                }
                            }}
                            options={[
                                {
                                    value: 'launchpad' as const,
                                    label: (
                                        <>
                                            Launchpad{' '}
                                            <LemonTag size="small" type="highlight" className="ml-1">
                                                New
                                            </LemonTag>
                                        </>
                                    ),
                                    'data-attr': 'configure-home-modal-set-launchpad',
                                    tooltip: 'An AI-powered home with quick actions and recent items',
                                },
                                {
                                    value: 'search' as const,
                                    label: 'Search',
                                    'data-attr': 'configure-home-modal-set-search',
                                    tooltip: 'A search page to quickly find anything in your project',
                                },
                                {
                                    value: 'default_dashboard' as const,
                                    label: 'Default dashboard',
                                    'data-attr': 'configure-home-modal-set-default-dashboard',
                                    tooltip: "Open your project's default dashboard when you go home",
                                },
                            ]}
                        />
                    </div>
                    {showDashboardPicker && (
                        <section className="space-y-3 bg-surface-secondary rounded-lg p-3 border">
                            <div className="flex flex-col">
                                <h4 className="text-base font-semibold text-primary m-0">
                                    Set default dashboard (project based)
                                </h4>
                                <p className="text-sm text-tertiary m-0">
                                    This dashboard opens by default for everyone who has not set a custom homepage.
                                </p>
                            </div>
                            <LemonSelect<number | null>
                                className="w-full"
                                fullWidth
                                options={projectDefaultDashboardOptions}
                                value={projectDefaultDashboardId}
                                data-attr="configure-home-modal-set-default-dashboard-select"
                                onChange={(dashboardId) => {
                                    posthog.capture('homepage configure default dashboard changed')
                                    updateCurrentTeam({ primary_dashboard: dashboardId ?? null })
                                    if (dashboardId) {
                                        setPendingMode(null)
                                        setHomepage({
                                            id: `homepage-dashboard-${dashboardId}`,
                                            pathname: urls.dashboard(dashboardId),
                                            search: '',
                                            hash: '',
                                            title: 'Default dashboard',
                                            iconType: 'dashboard',
                                            sceneId: Scene.Dashboard,
                                            sceneKey: `dashboard-${dashboardId}`,
                                            sceneParams: emptySceneParams,
                                        })
                                    }
                                }}
                                disabledReason={dashboardsLoading ? 'Loading dashboards…' : undefined}
                            />
                        </section>
                    )}
                </div>
            </section>
        </LemonModal>
    )
}

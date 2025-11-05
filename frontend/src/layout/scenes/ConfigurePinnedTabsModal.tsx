import { useActions, useValues } from 'kea'

import { LemonButton, LemonSelect, LemonSelectOptions, LemonTag } from '@posthog/lemon-ui'

import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { dashboardsModel } from '~/models/dashboardsModel'
import { FileSystemIconType } from '~/queries/schema/schema-general'
import { sceneLogic } from '~/scenes/sceneLogic'
import { Scene, SceneTab } from '~/scenes/sceneTypes'
import { emptySceneParams } from '~/scenes/scenes'
import { teamLogic } from '~/scenes/teamLogic'
import { urls } from '~/scenes/urls'

export interface ConfigurePinnedTabsModalProps {
    isOpen: boolean
    onClose: () => void
}

export function ConfigurePinnedTabsModal({ isOpen, onClose }: ConfigurePinnedTabsModalProps): JSX.Element {
    const { tabs, homepage } = useValues(sceneLogic)
    const { currentTeam } = useValues(teamLogic)
    const { rawDashboards, nameSortedDashboards, dashboardsLoading } = useValues(dashboardsModel)
    const { pinTab, unpinTab, setHomepage } = useActions(sceneLogic)
    const { updateCurrentTeam } = useActions(teamLogic)

    const homepageTabForDisplay = homepage ? (tabs.find((tab) => tab.id === homepage.id) ?? homepage) : null
    const isUsingProjectDefault = !homepage
    const isUsingNewTabHomepage = homepage?.sceneId === Scene.NewTab

    const projectDefaultDashboardId = currentTeam?.primary_dashboard ?? null
    const projectDefaultDashboard =
        projectDefaultDashboardId != null ? rawDashboards?.[projectDefaultDashboardId] : null
    const projectDefaultDashboardName =
        projectDefaultDashboard?.name ??
        (projectDefaultDashboardId != null ? `Dashboard #${projectDefaultDashboardId}` : null)
    const projectDefaultSubtitle = projectDefaultDashboardName ?? 'Not configured'

    const homepageDisplayTitle = homepageTabForDisplay
        ? homepageTabForDisplay.customTitle || homepageTabForDisplay.title
        : "Project's default dashboard"
    const homepageSubtitle = isUsingProjectDefault
        ? projectDefaultSubtitle
        : isUsingNewTabHomepage
          ? 'New tab page'
          : null

    const projectDefaultDashboardOptions: LemonSelectOptions<number | null> = [
        { value: null, label: 'No default dashboard (open new tab)' },
        ...nameSortedDashboards.map((dashboard) => ({
            value: dashboard.id,
            label: dashboard.name || 'Untitled',
        })),
    ]

    const homepageIcon = homepageTabForDisplay?.iconType
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
        title: 'New tab',
        iconType: 'blank',
        active: false,
        pinned: true,
        sceneId: Scene.NewTab,
        sceneKey: 'newTab',
        sceneParams: emptySceneParams,
    }

    const homepageAction = (tab: SceneTab): { label: string; onClick: () => void } =>
        homepage?.id === tab.id
            ? { label: 'Unset homepage', onClick: () => setHomepage(null) }
            : { label: 'Set as homepage', onClick: () => setHomepage(tab) }

    const personalPinnedTabs = tabs.filter((tab) => tab.pinned)
    const regularTabs = tabs.filter((tab) => !tab.pinned)

    const renderTabRow = (
        tab: SceneTab,
        actions: { label: string; onClick: () => void }[],
        isHomepage = false
    ): JSX.Element => (
        <div
            key={tab.id}
            className="flex items-center justify-between gap-3 rounded-lg border border-border px-3 py-2 bg-surface-primary"
        >
            <div className="flex min-w-0 items-center gap-2">
                <span className="shrink-0 text-lg text-muted-alt">
                    {iconForType(
                        tab.iconType && tab.iconType !== 'loading' && tab.iconType !== 'blank'
                            ? (tab.iconType as FileSystemIconType)
                            : undefined
                    )}
                </span>
                <div className="flex items-center gap-2 truncate">
                    <div className="truncate font-medium text-primary">{tab.customTitle || tab.title}</div>
                    {isHomepage && <LemonTag size="small">Homepage</LemonTag>}
                </div>
            </div>
            <div className="flex flex-wrap gap-2">
                {actions.map(({ label, onClick }) => (
                    <LemonButton key={label} size="small" type="secondary" onClick={onClick}>
                        {label}
                    </LemonButton>
                ))}
            </div>
        </div>
    )

    const renderSection = (
        title: string,
        description: string,
        sectionTabs: SceneTab[],
        actions: (tab: SceneTab) => { label: string; onClick: () => void }[],
        emptyState: string,
        isHomepage?: (tab: SceneTab) => boolean
    ): JSX.Element => (
        <section className="space-y-3">
            <div>
                <h3 className="text-lg font-semibold text-primary">{title}</h3>
                <p className="text-sm text-muted-alt">{description}</p>
            </div>
            {sectionTabs.length > 0 ? (
                <div className="space-y-2">
                    {sectionTabs.map((tab) => renderTabRow(tab, actions(tab), isHomepage?.(tab)))}
                </div>
            ) : (
                <div className="rounded-lg border border-dashed border-border px-3 py-6 text-center text-sm text-muted">
                    {emptyState}
                </div>
            )}
        </section>
    )

    return (
        <LemonModal isOpen={isOpen} onClose={onClose} title="Configure tabs & home" width="48rem">
            <div className="space-y-6">
                {renderSection(
                    'Pinned tabs',
                    'Pinned tabs are only visible to you and persist with the project.',
                    personalPinnedTabs,
                    (tab) => [homepageAction(tab), { label: 'Unpin', onClick: () => unpinTab(tab.id) }],
                    'No pinned tabs yet.',
                    (tab) => homepage?.id === tab.id
                )}
                {renderSection(
                    'Regular tabs (unpinned)',
                    'Regular tabs are discarded when you close your browser.',
                    regularTabs,
                    (tab) => [homepageAction(tab), { label: 'Pin', onClick: () => pinTab(tab.id) }],
                    'No regular tabs available to pin.',
                    (tab) => homepage?.id === tab.id
                )}
                <section className="space-y-3">
                    <div>
                        <h3 className="text-lg font-semibold text-primary">Homepage</h3>
                        <p className="text-sm text-muted-alt">Choose your personal homepage for this project.</p>
                    </div>
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
                        <div className="flex flex-wrap gap-2">
                            <LemonButton
                                size="small"
                                type="secondary"
                                onClick={() => setHomepage(null)}
                                disabled={isUsingProjectDefault}
                            >
                                Use default dashboard
                            </LemonButton>
                            <LemonButton
                                size="small"
                                type="secondary"
                                onClick={() => setHomepage(newTabHomepage)}
                                disabled={isUsingNewTabHomepage}
                            >
                                Use new tab page
                            </LemonButton>
                        </div>
                    </div>
                </section>
                <section className="space-y-3">
                    <div>
                        <h3 className="text-lg font-semibold text-primary">Project default dashboard</h3>
                        <p className="text-sm text-muted-alt">
                            This dashboard opens by default for everyone who has not set a custom homepage.
                        </p>
                    </div>
                    <LemonSelect<number | null>
                        className="w-full"
                        fullWidth
                        options={projectDefaultDashboardOptions}
                        value={projectDefaultDashboardId}
                        onChange={(dashboardId) => updateCurrentTeam({ primary_dashboard: dashboardId ?? null })}
                        disabledReason={dashboardsLoading ? 'Loading dashboards…' : undefined}
                    />
                </section>
            </div>
        </LemonModal>
    )
}

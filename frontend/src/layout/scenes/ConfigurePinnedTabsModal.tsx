import { useActions, useValues } from 'kea'

import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { FileSystemIconType } from '~/queries/schema/schema-general'
import { sceneLogic } from '~/scenes/sceneLogic'
import { Scene, SceneTab } from '~/scenes/sceneTypes'
import { emptySceneParams } from '~/scenes/scenes'
import { urls } from '~/scenes/urls'

export interface ConfigurePinnedTabsModalProps {
    isOpen: boolean
    onClose: () => void
}

export function ConfigurePinnedTabsModal({ isOpen, onClose }: ConfigurePinnedTabsModalProps): JSX.Element {
    const { tabs, homepage } = useValues(sceneLogic)
    const { pinTab, unpinTab, setHomepage } = useActions(sceneLogic)

    const homepageTabForDisplay = homepage ? (tabs.find((tab) => tab.id === homepage.id) ?? homepage) : null
    const isUsingProjectDefault = !homepage
    const isUsingNewTabHomepage = homepage?.sceneId === Scene.NewTab

    const homepageDisplayTitle = homepageTabForDisplay
        ? homepageTabForDisplay.customTitle || homepageTabForDisplay.title
        : 'Project homepage'
    const homepageDescription = isUsingProjectDefault
        ? 'Currently using the project default homepage.'
        : isUsingNewTabHomepage
          ? 'Currently set to the new tab page.'
          : `Currently set to ${homepageDisplayTitle}.`

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
                    'Your personal pinned tabs',
                    'Pinned tabs are visible only to you and stay available when you come back.',
                    personalPinnedTabs,
                    (tab) => [homepageAction(tab), { label: 'Unpin', onClick: () => unpinTab(tab.id) }],
                    'No personal pinned tabs yet.',
                    (tab) => homepage?.id === tab.id
                )}
                {renderSection(
                    'Regular tabs (unpinned)',
                    'Regular tabs are discarded when you close your browser session.',
                    regularTabs,
                    (tab) => [homepageAction(tab), { label: 'Pin', onClick: () => pinTab(tab.id) }],
                    'No regular tabs available to pin.',
                    (tab) => homepage?.id === tab.id
                )}
                <section className="space-y-3">
                    <div>
                        <h3 className="text-lg font-semibold text-primary">Homepage</h3>
                        <p className="text-sm text-muted-alt">Choose where you land when you open PostHog.</p>
                    </div>
                    <div className="flex items-center justify-between gap-3 rounded-lg border border-border px-3 py-2 bg-surface-primary">
                        <div className="flex min-w-0 items-center gap-2">
                            <span className="shrink-0 text-lg text-muted-alt">{homepageIconElement}</span>
                            <div className="min-w-0">
                                <div className="truncate font-medium text-primary">Homepage</div>
                                <div className="truncate text-xs text-muted">{homepageDescription}</div>
                            </div>
                        </div>
                        <div className="flex flex-wrap gap-2">
                            <LemonButton
                                size="small"
                                type="secondary"
                                onClick={() => setHomepage(null)}
                                disabled={isUsingProjectDefault}
                            >
                                Use project default
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
            </div>
        </LemonModal>
    )
}

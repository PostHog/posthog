import { useActions, useValues } from 'kea'

import { LemonButton, LemonLabel, LemonModal } from '@posthog/lemon-ui'

import { HomepageConfiguration } from '~/layout/scenes/HomepageConfiguration'

import { projectTreeDataLogic } from '../../ProjectTree/projectTreeDataLogic'
import { navProductsTabLogic } from './navProductsTabLogic'
import { SidebarSuggestionsSetting } from './SidebarSuggestionsSetting'
import { StarredProductsPicker } from './StarredProductsPicker'

export function CustomizeSidebarModal(): JSX.Element {
    const { customizeSidebarOpen, starredProductsSaving, hasDraftStarredChanges } = useValues(navProductsTabLogic)
    const { setCustomizeSidebarOpen, saveStarredProducts } = useActions(navProductsTabLogic)
    const { shortcutDataHasLoaded } = useValues(projectTreeDataLogic)

    return (
        <LemonModal
            title="Customize sidebar"
            isOpen={customizeSidebarOpen}
            onClose={() => setCustomizeSidebarOpen(false)}
            hasUnsavedInput={hasDraftStarredChanges}
            width={720}
            footer={
                <div className="flex flex-wrap items-center gap-2 w-full">
                    <div className="flex-1">
                        <p className="text-xs text-secondary mb-0">
                            Tip: Drag starred items in the sidebar to rearrange them.
                        </p>
                    </div>
                    <LemonButton
                        type="secondary"
                        onClick={() => setCustomizeSidebarOpen(false)}
                        disabledReason={starredProductsSaving ? 'Saving your starred products' : undefined}
                        data-attr="customize-sidebar-cancel"
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={saveStarredProducts}
                        loading={starredProductsSaving}
                        disabledReason={!shortcutDataHasLoaded ? 'Loading your starred products' : undefined}
                        data-attr="customize-sidebar-save"
                    >
                        Save
                    </LemonButton>
                </div>
            }
        >
            <div className="flex flex-col gap-6">
                <section className="flex flex-col gap-2">
                    <div>
                        <LemonLabel>Homepage</LemonLabel>
                        <p className="text-xs text-secondary mb-0">The page that opens when you select Home.</p>
                    </div>
                    <HomepageConfiguration />
                </section>
                <SidebarSuggestionsSetting />
                <StarredProductsPicker />
            </div>
        </LemonModal>
    )
}

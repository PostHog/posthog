import { useActions, useValues } from 'kea'

import { IconEllipsis } from '@posthog/icons'
import { LemonButton, LemonInput, Spinner } from '@posthog/lemon-ui'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'

import { panelLayoutLogic } from '../../panelLayoutLogic'
import { ProjectTree } from '../../ProjectTree/ProjectTree'
import { projectTreeDataLogic } from '../../ProjectTree/projectTreeDataLogic'
import { NavAppRow } from './NavAppRow'
import { APPS_STARRED_TREE_KEY, navAppsTabLogic } from './navAppsTabLogic'

export function NavTabApps(): JSX.Element {
    const { search, groupedItems } = useValues(navAppsTabLogic)
    const { setSearch } = useActions(navAppsTabLogic)
    const { shortcutData, shortcutDataHasLoaded } = useValues(projectTreeDataLogic)
    const { setActivePanelIdentifier, showLayoutPanel } = useActions(panelLayoutLogic)

    return (
        <div className="flex flex-col h-full min-h-0 group/colorful-product-icons colorful-product-icons-true">
            <div className="p-1">
                <LemonInput
                    type="search"
                    size="small"
                    className="min-h-[30px]"
                    placeholder="Search apps"
                    aria-label="Search apps"
                    value={search}
                    onChange={setSearch}
                    fullWidth
                    data-attr="nav-apps-search"
                />
            </div>
            <ScrollableShadows
                direction="vertical"
                className="flex-1 min-h-0"
                innerClassName="px-1 pb-2"
                styledScrollbars
            >
                <div className="flex items-center justify-between px-2 pt-1">
                    <span className="text-xs font-semibold text-secondary">Starred</span>
                    <LemonButton
                        size="xsmall"
                        icon={<IconEllipsis />}
                        tooltip="Manage starred items"
                        aria-label="Manage starred items"
                        data-attr="nav-apps-manage-starred"
                        onClick={() => {
                            setActivePanelIdentifier('Shortcuts')
                            showLayoutPanel(true)
                        }}
                    />
                </div>
                {!shortcutDataHasLoaded ? (
                    <Spinner className="m-2" />
                ) : shortcutData.length > 0 ? (
                    <ProjectTree
                        root="shortcuts://"
                        logicKey={APPS_STARRED_TREE_KEY}
                        onlyTree
                        showShortcutHelp={false}
                    />
                ) : (
                    <p className="text-xs text-tertiary px-2 py-1 mb-0">Star apps or files to keep them here.</p>
                )}
                {groupedItems.map((group) => (
                    <section key={group.label} aria-label={group.label}>
                        <h3 className="px-2 pt-3 pb-1 mb-0 text-xs font-semibold text-secondary">{group.label}</h3>
                        <div className="flex flex-col gap-px">
                            {group.items.map((item) => (
                                <NavAppRow key={`${item.path}-${item.href}`} item={item} />
                            ))}
                        </div>
                    </section>
                ))}
                {groupedItems.length === 0 && (
                    <p className="text-xs text-tertiary px-2 py-2">No apps found. Try a different search.</p>
                )}
            </ScrollableShadows>
        </div>
    )
}

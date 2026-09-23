import { useActions, useValues } from 'kea'

import { IconSearch } from '@posthog/icons'
import { LemonInput, Spinner } from '@posthog/lemon-ui'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'

import { ProjectTree } from '../../ProjectTree/ProjectTree'
import { projectTreeDataLogic } from '../../ProjectTree/projectTreeDataLogic'
import { projectTreeLogic } from '../../ProjectTree/projectTreeLogic'
import { NavAppRow } from './NavAppRow'
import { APPS_STARRED_TREE_KEY, navAppsTabLogic } from './navAppsTabLogic'
import { NavAppTooltip } from './NavAppTooltip'
import { NavTabSection } from './NavTabSection'

export function NavTabApps(): JSX.Element {
    const { search, allItems, groupedItems, jevEnabled, isJevSearch, appRankings, appRankingsLoading } =
        useValues(navAppsTabLogic)
    const { setSearch } = useActions(navAppsTabLogic)
    const { shortcutDataHasLoaded } = useValues(projectTreeDataLogic)
    const { fullFileSystemFiltered: starredApps } = useValues(
        projectTreeLogic({ key: APPS_STARRED_TREE_KEY, root: 'shortcuts://', shortcutScope: 'apps' })
    )

    return (
        <div className="flex flex-col h-full min-h-0 group/colorful-product-icons colorful-product-icons-true">
            <div className="p-1">
                <LemonInput
                    type="search"
                    prefix={
                        <div className="flex items-center justify-center size-4 ml-[2px] mr-px">
                            <IconSearch className="size-4" />
                        </div>
                    }
                    size="small"
                    className="min-h-[30px]"
                    placeholder={jevEnabled ? 'Jev apps' : 'Filter apps'}
                    aria-label={jevEnabled ? 'Jev apps' : 'Filter apps'}
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
                {!isJevSearch && (!search.trim() || !shortcutDataHasLoaded || starredApps.length > 0) && (
                    <NavTabSection
                        label="Starred"
                        dataAttr="nav-apps-starred-toggle"
                        key={`starred-${!!search.trim()}`}
                    >
                        {!shortcutDataHasLoaded ? (
                            <Spinner className="m-2" />
                        ) : starredApps.length > 0 ? (
                            <ProjectTree
                                root="shortcuts://"
                                shortcutScope="apps"
                                logicKey={APPS_STARRED_TREE_KEY}
                                onlyTree
                                showShortcutHelp={false}
                                renderItemTooltip={(item) => {
                                    const app = allItems.find((app) => app.href === item.record?.href)
                                    return app ? <NavAppTooltip item={app} /> : undefined
                                }}
                            />
                        ) : (
                            <p className="text-xs text-tertiary px-2 py-1 mb-0">Star apps to keep them here.</p>
                        )}
                    </NavTabSection>
                )}
                <NavTabSection
                    label={isJevSearch ? 'Results' : 'Project'}
                    collapsedLabel="All apps"
                    dataAttr="nav-apps-project-toggle"
                    key={`project-${!!search.trim()}`}
                >
                    {isJevSearch && appRankingsLoading && (
                        <div className="flex items-center gap-2 px-2 py-2 text-xs text-secondary" role="status">
                            <Spinner />
                            <span>Finding apps…</span>
                        </div>
                    )}
                    {isJevSearch && !appRankingsLoading && appRankings?.failed && (
                        <p className="text-xs text-secondary px-2 py-2" role="status">
                            Jev is unavailable. Showing name matches. Try your search again in a moment.
                        </p>
                    )}
                    {groupedItems.map((group) => (
                        <section key={group.label} aria-label={group.label}>
                            {group.label !== 'Project' && (
                                <h3 className="px-2 pt-3 pb-1 mb-0 text-xs font-semibold text-secondary">
                                    {group.label}
                                </h3>
                            )}
                            <div className="flex flex-col gap-px">
                                {group.items.map((item) => (
                                    <NavAppRow key={`${item.path}-${item.href}`} item={item} />
                                ))}
                            </div>
                        </section>
                    ))}
                    {groupedItems.length === 0 && !(isJevSearch && appRankingsLoading) && (
                        <p className="text-xs text-tertiary px-2 py-2">No apps found. Try a different search.</p>
                    )}
                </NavTabSection>
            </ScrollableShadows>
        </div>
    )
}

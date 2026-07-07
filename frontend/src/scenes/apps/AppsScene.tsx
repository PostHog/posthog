import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useRef } from 'react'

import { LemonInput, LemonTag } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'
import { cn } from 'lib/utils/css-classes'
import { SceneExport } from 'scenes/sceneTypes'

import { SearchHighlightMultiple } from '~/layout/navigation-3000/components/SearchHighlight'
import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { HomeViewToggle } from '~/layout/scenes/HomeViewToggle'
import { FileSystemIconType } from '~/queries/schema/schema-general'

import { appsSceneLogic, getAppItemName } from './appsSceneLogic'

export const scene: SceneExport = {
    component: AppsScene,
    logic: appsSceneLogic,
}

export function AppsScene(): JSX.Element {
    const { searchTerm, filteredAppItems } = useValues(appsSceneLogic)
    const { setSearchTerm } = useActions(appsSceneLogic)
    const hasSearch = searchTerm.trim().length > 0
    const searchRef = useRef<HTMLInputElement>(null)
    const gridRef = useRef<HTMLDivElement>(null)

    function getGridLinks(): HTMLAnchorElement[] {
        return Array.from(gridRef.current?.querySelectorAll<HTMLAnchorElement>('[data-attr="apps-grid-item"]') ?? [])
    }

    // The grid is responsive (auto-fill), so the column count comes from the rendered layout
    function getColumnCount(links: HTMLAnchorElement[]): number {
        const firstTop = links[0]?.offsetTop
        let columns = 0
        for (const link of links) {
            if (link.offsetTop !== firstTop) {
                break
            }
            columns += 1
        }
        return Math.max(columns, 1)
    }

    function handleGridKeyDown(e: React.KeyboardEvent, index: number): void {
        const links = getGridLinks()
        const columns = getColumnCount(links)
        let next: number
        switch (e.key) {
            case 'ArrowRight':
                next = index + 1
                break
            case 'ArrowLeft':
                next = index - 1
                break
            case 'ArrowDown':
                next = index + columns
                break
            case 'ArrowUp':
                next = index - columns
                break
            default:
                return
        }
        e.preventDefault()
        if (next < 0) {
            searchRef.current?.focus()
        } else if (next < links.length) {
            links[next].focus()
        }
    }

    return (
        <div className="relative h-full overflow-y-auto">
            <HomeViewToggle current="apps" />
            <div className="absolute top-2 right-2 z-20">
                <LemonInput
                    type="search"
                    size="small"
                    className="w-60"
                    placeholder="Search apps"
                    value={searchTerm}
                    onChange={setSearchTerm}
                    onPressEnter={() => {
                        const first = filteredAppItems[0]
                        if (first?.href) {
                            router.actions.push(first.href)
                        }
                    }}
                    onKeyDown={(e) => {
                        if (e.key === 'ArrowDown') {
                            e.preventDefault()
                            getGridLinks()[0]?.focus()
                        }
                    }}
                    inputRef={searchRef}
                    autoFocus
                    data-attr="apps-scene-search"
                />
            </div>
            <div className="max-w-[1280px] mx-auto px-8 pt-14 pb-8 group/colorful-product-icons colorful-product-icons-true">
                <div ref={gridRef} className="grid grid-cols-[repeat(auto-fill,minmax(10rem,1fr))] gap-2">
                    {filteredAppItems.map((item, index) => (
                        <Link
                            key={getAppItemName(item)}
                            to={item.href}
                            className={cn(
                                'flex flex-col items-center justify-center gap-2 rounded-lg p-4 bg-surface-primary hover:bg-surface-secondary transition-colors text-primary hover:text-primary',
                                // Enter opens the first match, so point it out while searching
                                hasSearch && index === 0 && 'ring-1 ring-accent'
                            )}
                            onKeyDown={(e) => handleGridKeyDown(e, index)}
                            data-attr="apps-grid-item"
                        >
                            <span className="text-2xl [&_svg]:size-8">
                                {iconForType(
                                    (item.iconType ?? (item.type as FileSystemIconType)) || undefined,
                                    item.iconColor
                                )}
                            </span>
                            <span className="text-sm font-medium text-center">
                                <SearchHighlightMultiple string={getAppItemName(item)} substring={searchTerm} />
                                {item.tags?.map((tag) => (
                                    <LemonTag
                                        key={tag}
                                        size="small"
                                        type={tag === 'alpha' ? 'completion' : 'warning'}
                                        className="ml-1 uppercase"
                                    >
                                        {tag}
                                    </LemonTag>
                                ))}
                            </span>
                        </Link>
                    ))}
                </div>
                {filteredAppItems.length === 0 && (
                    <div className="text-center text-secondary pt-8">No apps match "{searchTerm}"</div>
                )}
            </div>
        </div>
    )
}

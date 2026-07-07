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
    const { searchTerm, filteredAppItems, selectedIndex } = useValues(appsSceneLogic)
    const { setSearchTerm, setSelectedIndex } = useActions(appsSceneLogic)
    const gridRef = useRef<HTMLDivElement>(null)

    // The grid is responsive (auto-fill), so the column count comes from the rendered layout
    function getColumnCount(): number {
        const links = Array.from(
            gridRef.current?.querySelectorAll<HTMLAnchorElement>('[data-attr="apps-grid-item"]') ?? []
        )
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

    // Arrow keys move the selection while the search field keeps focus, so you can keep typing.
    // Enter is handled here too: LemonInput's own Enter handling (onPressEnter) is overridden
    // the moment a custom onKeyDown prop is passed, as the props spread replaces it.
    function handleSearchKeyDown(e: React.KeyboardEvent<HTMLInputElement>): void {
        if (e.key === 'Enter' && !e.nativeEvent.isComposing) {
            const selected = filteredAppItems[selectedIndex]
            if (selected?.href) {
                router.actions.push(selected.href)
            }
            return
        }
        let next: number
        switch (e.key) {
            case 'ArrowRight':
                next = selectedIndex + 1
                break
            case 'ArrowLeft':
                next = selectedIndex - 1
                break
            case 'ArrowDown':
                next = selectedIndex + getColumnCount()
                break
            case 'ArrowUp':
                next = selectedIndex - getColumnCount()
                break
            default:
                return
        }
        e.preventDefault()
        if (next >= 0 && next < filteredAppItems.length) {
            setSelectedIndex(next)
            gridRef.current
                ?.querySelectorAll<HTMLAnchorElement>('[data-attr="apps-grid-item"]')
                [next]?.scrollIntoView({ block: 'nearest' })
        }
    }

    return (
        <div className="relative h-full overflow-y-auto">
            {/* flex-wrap drops the search field onto its own line when the page gets too narrow */}
            <div className="flex flex-wrap items-center gap-2 p-2">
                <HomeViewToggle current="apps" inline />
                <LemonInput
                    type="search"
                    size="small"
                    className="w-60 ml-auto"
                    placeholder="Search apps"
                    value={searchTerm}
                    onChange={setSearchTerm}
                    onKeyDown={handleSearchKeyDown}
                    autoFocus
                    data-attr="apps-scene-search"
                />
            </div>
            <div className="max-w-[1280px] mx-auto px-8 pt-6 pb-8 group/colorful-product-icons colorful-product-icons-true">
                <div ref={gridRef} className="grid grid-cols-[repeat(auto-fill,minmax(10rem,1fr))] gap-2">
                    {filteredAppItems.map((item, index) => (
                        <Link
                            key={getAppItemName(item)}
                            to={item.href}
                            className={cn(
                                'flex flex-col items-center justify-center gap-2 rounded-lg p-4 bg-surface-primary hover:bg-surface-secondary transition-colors text-primary hover:text-primary',
                                // Arrow keys move this selection, Enter opens it
                                index === selectedIndex && 'ring-1 ring-accent'
                            )}
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

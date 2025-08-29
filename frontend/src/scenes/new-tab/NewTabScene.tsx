import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Link } from 'lib/lemon-ui/Link'
import { cn } from 'lib/utils/css-classes'
import { newTabSceneLogic } from 'scenes/new-tab/newTabSceneLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { SearchHighlightMultiple } from '~/layout/navigation-3000/components/SearchHighlight'

export const scene: SceneExport = {
    component: NewTabScene,
    logic: newTabSceneLogic,
}

const generateHash = (string: string): number => {
    let hash = 0
    for (const char of string) {
        hash = (hash << 5) - hash + char.charCodeAt(0)
        hash |= 0 // Convert to 32bit integer
    }
    return Math.abs(hash)
}

export function NewTabScene({ tabId }: { tabId?: string } = {}): JSX.Element {
    const { filteredItemsGrid, search, selectedItem, focused } = useValues(newTabSceneLogic({ tabId }))
    const { setSearch, selectNext, selectPrevious, onFocus, onBlur, onSubmit } = useActions(newTabSceneLogic({ tabId }))

    // pastel palette (cycle through)
    const swatches = [
        'bg-sky-500/10 text-sky-700 dark:bg-sky-500/20 dark:text-sky-100',
        'bg-emerald-500/10 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-100',
        'bg-violet-500/10 text-violet-700 dark:bg-violet-500/20 dark:text-violet-100',
        'bg-amber-500/10 text-amber-700 dark:bg-amber-500/20 dark:text-amber-100',
        'bg-pink-500/10 text-pink-700 dark:bg-pink-500/20 dark:text-pink-100',
        'bg-stone-500/10 text-stone-700 dark:bg-stone-500/20 dark:text-stone-100',
    ]
    const darkSwatches = [
        'bg-sky-800/80 text-sky-300 dark:bg-sky-300/80 dark:text-sky-700',
        'bg-emerald-800/80 text-emerald-300 dark:bg-emerald-300/80 dark:text-emerald-700',
        'bg-violet-800/80 text-violet-300 dark:bg-violet-300/80 dark:text-violet-700',
        'bg-amber-800/80 text-amber-300 dark:bg-amber-300/80 dark:text-amber-700',
        'bg-pink-800/80 text-pink-300 dark:bg-pink-300/80 dark:text-pink-700',
        'bg-stone-800/80 text-stone-300 dark:bg-stone-300/80 dark:text-stone-700',
    ]

    // scroll it to view
    useEffect(() => {
        if (selectedItem) {
            const element = document.querySelector('.selected-new-tab-item')
            element?.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'center' })
        }
    }, [selectedItem])

    return (
        <div className="w-full py-24">
            <div className="flex gap-2 max-w-[800px] px-8 m-auto mt-2 mb-12">
                <input
                    type="text"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                            e.preventDefault()
                            e.stopPropagation()
                            onSubmit()
                        }
                        if (e.key === 'Tab') {
                            e.preventDefault()
                            e.stopPropagation()
                            if (e.shiftKey) {
                                selectPrevious()
                            } else {
                                selectNext()
                            }
                        }
                    }}
                    onFocus={onFocus}
                    onBlur={onBlur}
                    autoFocus
                    placeholder="Type to filter, then press ENTER to run and (shift+)tab to move."
                    className="flex-1 px-4 py-3 rounded-lg border border-border dark:border-border-dark bg-white dark:bg-gray-900 text-primary dark:text-primary-dark text-base focus:ring-2 focus:ring-red dark:focus:ring-yellow focus:border-transparent transition-all"
                />
                <LemonButton
                    type="primary"
                    disabledReason={
                        !search.trim()
                            ? 'Please write a filter'
                            : Object.keys(filteredItemsGrid).length === 0
                              ? 'No results'
                              : ''
                    }
                    onClick={onSubmit}
                >
                    Take me there
                </LemonButton>
            </div>

            {filteredItemsGrid.map(({ category, types }) => (
                <div className="w-full overflow-auto p-4 px-12 max-w-[880px] m-auto" key={category}>
                    <div className="px-2 py-8 text-center">
                        {search ? <SearchHighlightMultiple string={category} substring={search} /> : category}
                    </div>
                    <div
                        className="grid gap-12"
                        style={{
                            gridTemplateColumns: 'repeat(auto-fit, minmax(7rem, 1fr))',
                        }}
                    >
                        {types.map((qt) => (
                            <div key={qt.name} className="text-center m-auto">
                                <Link
                                    to={qt.href}
                                    className={cn(
                                        'group flex flex-col items-center text-center cursor-pointer select-none focus:outline-none',
                                        focused && selectedItem?.type === qt ? 'underline selected-new-tab-item' : ''
                                    )}
                                >
                                    <div
                                        className={`flex items-center justify-center w-16 h-16 rounded-xl shadow-sm group-hover:shadow-md transition ${
                                            focused && selectedItem?.type === qt
                                                ? darkSwatches[generateHash(qt.name) % darkSwatches.length]
                                                : swatches[generateHash(qt.name) % swatches.length]
                                        }`}
                                    >
                                        <span className="text-2xl font-semibold">{qt.icon ?? qt.name[0]}</span>
                                    </div>
                                    <span className="mt-2 w-full text-xs font-medium truncate px-1 text-primary">
                                        {search ? (
                                            <SearchHighlightMultiple string={qt.name} substring={search} />
                                        ) : (
                                            qt.name
                                        )}
                                    </span>
                                </Link>
                            </div>
                        ))}
                    </div>
                </div>
            ))}
        </div>
    )
}

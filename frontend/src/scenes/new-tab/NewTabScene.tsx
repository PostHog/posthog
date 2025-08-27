import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

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

export function NewTabScene({ tabId }: { tabId?: string } = {}): JSX.Element {
    const { filteredItemsGrid, search } = useValues(newTabSceneLogic({ tabId }))
    const { setSearch } = useActions(newTabSceneLogic({ tabId }))

    const handleSubmit = (): void => {
        if (filteredItemsGrid.length > 0 && filteredItemsGrid[0].types.length > 0) {
            const firstItem = filteredItemsGrid[0].types[0]
            if (firstItem.href) {
                router.actions.push(firstItem.href)
            }
        }
    }

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

    return (
        <div className="w-full py-24">
            <div className="flex gap-2 max-w-[800px] px-8 m-auto mt-2 mb-12">
                <input
                    type="text"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    onClick={() => setSearch('')}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                            handleSubmit()
                        }
                    }}
                    autoFocus
                    placeholder="Type to filter apps, press ENTER to run the first one."
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
                    onClick={handleSubmit}
                >
                    Take me there
                </LemonButton>
            </div>

            {filteredItemsGrid.map(({ category, types }, catIndex) => (
                <div className="w-full overflow-auto p-4 px-12 max-w-[880px] m-auto" key={catIndex}>
                    <div className="px-2 py-8 text-center">
                        {search ? <SearchHighlightMultiple string={category} substring={search} /> : category}
                    </div>
                    <div
                        className="grid gap-12"
                        style={{
                            gridTemplateColumns: 'repeat(auto-fit, minmax(7rem, 1fr))',
                        }}
                    >
                        {types.map((qt, index) => (
                            <div key={qt.name} className="text-center m-auto">
                                <Link
                                    to={qt.href}
                                    className={cn(
                                        'group flex flex-col items-center text-center cursor-pointer select-none focus:outline-none',
                                        index === 0 && catIndex === 0 && search ? 'underline' : ''
                                    )}
                                >
                                    <div
                                        className={`flex items-center justify-center w-16 h-16 rounded-xl shadow-sm group-hover:shadow-md transition ${
                                            index === 0 && catIndex === 0 && search
                                                ? darkSwatches[(index + catIndex * 4) % darkSwatches.length]
                                                : swatches[(index + catIndex * 4) % swatches.length]
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

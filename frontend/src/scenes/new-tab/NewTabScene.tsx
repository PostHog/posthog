import { SceneExport } from 'scenes/sceneTypes'
import { useValues } from 'kea'
import { useState } from 'react'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Link } from 'lib/lemon-ui/Link'
import { newTabSceneLogic } from 'scenes/new-tab/newTabSceneLogic'

export const scene: SceneExport = {
    component: NewTabScene,
}

export function NewTabScene(): JSX.Element {
    const { itemsGrid } = useValues(newTabSceneLogic)

    const [question, setQuestion] = useState('')
    const handleSubmit = (): void => {}

    // pastel palette (cycle through)
    const swatches = [
        'bg-sky-500/10 text-sky-700 dark:bg-sky-500/20 dark:text-sky-100',
        'bg-emerald-500/10 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-100',
        'bg-violet-500/10 text-violet-700 dark:bg-violet-500/20 dark:text-violet-100',
        'bg-amber-500/10 text-amber-700 dark:bg-amber-500/20 dark:text-amber-100',
        'bg-pink-500/10 text-pink-700 dark:bg-pink-500/20 dark:text-pink-100',
        'bg-stone-500/10 text-stone-700 dark:bg-stone-500/20 dark:text-stone-100',
    ]

    return (
        <div className="w-full py-24">
            <div className="w-full text-center pb-4 text-sm font-medium">Choose a program to run or just ask Max.</div>

            <div className="flex gap-2 max-w-[800px] px-8 m-auto mt-2 mb-12">
                <input
                    type="text"
                    value={question}
                    onChange={(e) => setQuestion(e.target.value)}
                    onClick={() => setQuestion('')}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                            handleSubmit()
                        }
                    }}
                    placeholder="How much wood would a woodchuck chuck if a woodchuck could chuck wood?"
                    className="flex-1 px-4 py-3 rounded-lg border border-border dark:border-border-dark bg-white dark:bg-gray-900 text-primary dark:text-primary-dark text-base focus:ring-2 focus:ring-red dark:focus:ring-yellow focus:border-transparent transition-all"
                />
                <LemonButton
                    type="primary"
                    disabledReason={!question.trim() ? 'Please ask a question' : null}
                    onClick={handleSubmit}
                >
                    Ask Max
                </LemonButton>
            </div>

            {itemsGrid.map(({ category, types }, catIndex) => (
                <div className="w-full overflow-auto p-4 px-12 max-w-[880px] m-auto" key={catIndex}>
                    <div className="px-2 py-8 text-center">{category}</div>
                    <div
                        className="grid gap-12"
                        style={{
                            gridTemplateColumns: 'repeat(auto-fit, minmax(7rem, 1fr))',
                        }}
                    >
                        {types.map((qt, i) => (
                            <div key={qt.name} className="text-center m-auto">
                                <Link
                                    to={qt.href}
                                    className="group flex flex-col items-center text-center cursor-pointer select-none focus:outline-none"
                                >
                                    <div
                                        className={`flex items-center justify-center w-16 h-16 rounded-xl shadow-sm group-hover:shadow-md transition ${
                                            swatches[(i + catIndex * 4) % swatches.length]
                                        }`}
                                    >
                                        <span className="text-2xl font-semibold">{qt.icon ?? qt.name[0]}</span>
                                    </div>
                                    <span className="mt-2 w-full text-xs font-medium truncate px-1 text-primary">
                                        {qt.name}
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

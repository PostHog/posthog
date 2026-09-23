import { useActions, useValues } from 'kea'

import { LemonInput } from '@posthog/lemon-ui'

import { osAppStoreSceneLogic } from './osAppStoreSceneLogic'
import { OsAppTile } from './OsAppTile'

/** The store front page: apps by the job they help with, then Beta, Labs and the built-in apps. */
export function OsAppStoreFront(): JSX.Element {
    const { visibleSections, search } = useValues(osAppStoreSceneLogic)
    const { setSearch } = useActions(osAppStoreSceneLogic)

    return (
        <div className="flex flex-col gap-6">
            <LemonInput
                type="search"
                placeholder="Search apps"
                value={search}
                onChange={setSearch}
                className="max-w-100"
                data-attr="os-app-store-search"
            />
            {visibleSections.length === 0 ? (
                <p className="text-secondary">No apps match your search. Try another name.</p>
            ) : (
                visibleSections.map((section) => (
                    <section key={section.key} aria-labelledby={`os-app-store-${section.key}`}>
                        <h2 id={`os-app-store-${section.key}`} className="mb-2 text-base font-semibold">
                            {section.title}
                        </h2>
                        <ul className="m-0 grid list-none grid-cols-[repeat(auto-fill,minmax(16rem,1fr))] gap-3 p-0">
                            {section.apps.map((app) => (
                                <OsAppTile key={app.key} app={app} />
                            ))}
                        </ul>
                    </section>
                ))
            )}
        </div>
    )
}

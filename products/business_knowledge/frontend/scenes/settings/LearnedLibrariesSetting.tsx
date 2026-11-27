import { useActions, useValues } from 'kea'

import { LemonCheckbox, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { learnedLibrariesLogic } from './learnedLibrariesLogic'

export function LearnedLibrariesSetting(): JSX.Element {
    const { libraries, librariesLoading, sortedLibraries, savingLibraryIds, lastReceivingLibraryId } =
        useValues(learnedLibrariesLogic)
    const { setReceivesLearnedSources, loadLibraries } = useActions(learnedLibrariesLogic)

    return (
        <div className="flex flex-col items-start gap-2 max-w-xl">
            <div className="flex flex-col gap-1">
                <h4 className="m-0 font-semibold">Libraries for learned sources</h4>
                <p className="m-0 text-secondary">
                    New sources learned from support tickets join every library you select. Sources already in a library
                    stay there.
                </p>
            </div>
            {librariesLoading && !libraries ? (
                <LemonSkeleton className="h-6 w-60" />
            ) : !libraries ? (
                <p className="m-0">
                    Couldn't load your libraries. <Link onClick={() => loadLibraries()}>Try again</Link>
                </p>
            ) : sortedLibraries.length === 0 ? (
                <p className="m-0 text-secondary">
                    You have no libraries yet. The first source learned from a ticket creates a library named Learned.
                </p>
            ) : (
                <div className="flex flex-col gap-1">
                    {sortedLibraries.map((library) => (
                        <LemonCheckbox
                            key={library.id}
                            checked={library.is_default}
                            onChange={(checked) => setReceivesLearnedSources(library.id, checked)}
                            label={library.name}
                            disabledReason={
                                savingLibraryIds.includes(library.id)
                                    ? 'Saving'
                                    : library.id === lastReceivingLibraryId
                                      ? 'At least one library must receive learned sources'
                                      : undefined
                            }
                            data-attr="business-knowledge-learned-sources-library"
                        />
                    ))}
                </div>
            )}
        </div>
    )
}

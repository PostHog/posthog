import { useActions, useValues } from 'kea'

import { Checkbox, Heading, Skeleton, Text } from '@posthog/quill'

import { businessKnowledgeSettingsLogic } from './businessKnowledgeSettingsLogic'
import { learnedLibrariesLogic } from './learnedLibrariesLogic'
import { QuillRetryText } from './QuillRetryText'

export function QuillLearnedLibrariesSetting(): JSX.Element | null {
    const { libraries, librariesLoading, sortedLibraries, savingLibraryIds, lastReceivingLibraryId } =
        useValues(learnedLibrariesLogic)
    const { setReceivesLearnedSources, loadLibraries } = useActions(learnedLibrariesLogic)
    const { settings } = useValues(businessKnowledgeSettingsLogic)

    // The choice only matters while learning is on.
    if (!settings?.learn_from_support_enabled) {
        return null
    }

    return (
        <div className="flex flex-col items-start gap-2 max-w-xl">
            <div className="flex flex-col gap-1">
                <Heading size="sm" render={<h3 className="m-0" />}>
                    Libraries for learned sources
                </Heading>
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    New sources learned from support tickets join every library you select. Sources already in a library
                    stay there.
                </Text>
            </div>
            {librariesLoading && !libraries ? (
                <Skeleton className="h-6 w-60" />
            ) : !libraries ? (
                <QuillRetryText message="Couldn't load your libraries." onRetry={() => loadLibraries()} />
            ) : sortedLibraries.length === 0 ? (
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    You have no libraries yet. The first source learned from a ticket creates a library named Learned.
                </Text>
            ) : (
                <div className="flex flex-col gap-2">
                    {sortedLibraries.map((library) => (
                        <Checkbox
                            key={library.id}
                            checked={library.is_default}
                            onCheckedChange={(checked: boolean) => setReceivesLearnedSources(library.id, checked)}
                            disabledReason={
                                savingLibraryIds.includes(library.id)
                                    ? 'Saving'
                                    : library.id === lastReceivingLibraryId
                                      ? 'At least one library must receive learned sources'
                                      : undefined
                            }
                            data-attr="business-knowledge-learned-sources-library"
                        >
                            {library.name}
                        </Checkbox>
                    ))}
                </div>
            )}
        </div>
    )
}

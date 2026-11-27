import { useActions, useValues } from 'kea'

import { Checkbox, Heading, Skeleton, Text } from '@posthog/quill'

import { learnedLibrariesLogic } from './learnedLibrariesLogic'
import { QuillRetryText } from './QuillRetryText'

export function QuillLearnedLibrariesSetting(): JSX.Element {
    const { libraries, librariesLoading, libraryRows } = useValues(learnedLibrariesLogic)
    const { setReceivesLearnedSources, loadLibraries } = useActions(learnedLibrariesLogic)

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
            ) : libraryRows.length === 0 ? (
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    You have no libraries yet. The first source learned from a ticket creates a library named Learned.
                </Text>
            ) : (
                <div className="flex flex-col gap-2">
                    {libraryRows.map((row) => (
                        <Checkbox
                            key={row.id}
                            checked={row.receivesLearnedSources}
                            onCheckedChange={(checked: boolean) => setReceivesLearnedSources(row.id, checked)}
                            disabledReason={row.disabledReason}
                            data-attr="business-knowledge-learned-sources-library"
                        >
                            {row.name}
                        </Checkbox>
                    ))}
                </div>
            )}
        </div>
    )
}

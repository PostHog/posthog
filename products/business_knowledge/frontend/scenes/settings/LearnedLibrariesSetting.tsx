import { useActions, useValues } from 'kea'

import { LemonCheckbox, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { businessKnowledgeSettingsLogic } from './businessKnowledgeSettingsLogic'
import { learnedLibrariesLogic } from './learnedLibrariesLogic'
import { QuillLearnedLibrariesSetting } from './QuillLearnedLibrariesSetting'

export function LearnedLibrariesSetting(): JSX.Element | null {
    const { libraries, librariesLoading, libraryRows } = useValues(learnedLibrariesLogic)
    const { setReceivesLearnedSources, loadLibraries } = useActions(learnedLibrariesLogic)
    const { settings } = useValues(businessKnowledgeSettingsLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (!settings?.learn_from_support_enabled) {
        return null
    }
    if (todayRailNav) {
        return <QuillLearnedLibrariesSetting />
    }

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
            ) : libraryRows.length === 0 ? (
                <p className="m-0 text-secondary">
                    You have no libraries yet. The first source learned from a ticket creates a library named Learned.
                </p>
            ) : (
                <div className="flex flex-col gap-1">
                    {libraryRows.map((row) => (
                        <LemonCheckbox
                            key={row.id}
                            checked={row.receivesLearnedSources}
                            onChange={(checked) => setReceivesLearnedSources(row.id, checked)}
                            label={row.name}
                            disabledReason={row.disabledReason}
                            data-attr="business-knowledge-learned-sources-library"
                        />
                    ))}
                </div>
            )}
        </div>
    )
}

import { useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { urls } from 'scenes/urls'

import { analyticsShareLogic } from './analyticsShareLogic'
import { AnalyticsSpaceGlyph } from './AnalyticsSpaceGlyph'

/** Picks the space an analysis is shared into. Lives in the Lemon scene headers, so it is a Lemon modal. */
export function ShareToSpaceModal(): JSX.Element {
    const { target, spaces, spacesLoading, sharing } = useValues(analyticsShareLogic)
    const { closeShareToSpace, shareToSpace } = useActions(analyticsShareLogic)

    return (
        <LemonModal
            isOpen={!!target}
            onClose={closeShareToSpace}
            title="Share into a space"
            description={target ? `Everyone in the space you pick will find "${target.name}" in Analytics.` : undefined}
            width={480}
        >
            {spacesLoading && !spaces.length ? (
                <div className="flex flex-col gap-2">
                    <LemonSkeleton className="h-10" />
                    <LemonSkeleton className="h-10" />
                </div>
            ) : !spaces.length ? (
                <div className="flex flex-col gap-2">
                    <p className="m-0 text-secondary">No spaces yet. Create one first, then share into it.</p>
                    <LemonButton type="secondary" to={urls.analyticsSpaces()} onClick={closeShareToSpace}>
                        Open spaces
                    </LemonButton>
                </div>
            ) : (
                <div className="flex flex-col gap-1">
                    {spaces.map((space) => (
                        <LemonButton
                            key={space.path}
                            type="tertiary"
                            fullWidth
                            icon={<AnalyticsSpaceGlyph name={space.name} size="md" />}
                            loading={sharing}
                            disabledReason={sharing ? 'Sharing…' : undefined}
                            onClick={() => shareToSpace(space)}
                            data-attr="analytics-share-to-space"
                        >
                            <span className="flex flex-col items-start">
                                <span>{space.name}</span>
                                <span className="text-xs text-secondary">
                                    {space.total === 0 ? 'Empty' : `${space.total} shared`}
                                </span>
                            </span>
                        </LemonButton>
                    ))}
                </div>
            )}
        </LemonModal>
    )
}

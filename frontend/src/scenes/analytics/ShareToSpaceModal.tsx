import { useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { urls } from 'scenes/urls'

import { analyticsShareLogic } from './analyticsShareLogic'
import { AnalyticsSpaceGlyph } from './AnalyticsSpaceGlyph'

/** Picks the space an item is shared into, or moved to. Lives in the Lemon scene headers, so it is a Lemon modal. */
export function ShareToSpaceModal(): JSX.Element {
    const { target, spaces, spacesLoading, sharing, currentSpace, entryLoading } = useValues(analyticsShareLogic)
    const { closeShareToSpace, shareToSpace } = useActions(analyticsShareLogic)
    const moving = !!currentSpace
    const loading = (spacesLoading && !spaces.length) || entryLoading

    return (
        <LemonModal
            isOpen={!!target}
            onClose={closeShareToSpace}
            title={moving ? 'Move to a collection' : 'Add to a collection'}
            description={
                target
                    ? moving
                        ? `"${target.name}" is in ${currentSpace}. Pick where it goes next.`
                        : `Pick the collection "${target.name}" goes in.`
                    : undefined
            }
            width={480}
        >
            {loading ? (
                <div className="flex flex-col gap-2">
                    <LemonSkeleton className="h-10" />
                    <LemonSkeleton className="h-10" />
                </div>
            ) : !spaces.length ? (
                <div className="flex flex-col gap-2">
                    <p className="m-0 text-secondary">No collections yet. Create one first, then add to it.</p>
                    <LemonButton type="secondary" to={urls.analyticsSpaces()} onClick={closeShareToSpace}>
                        Open collections
                    </LemonButton>
                </div>
            ) : (
                <div className="flex flex-col gap-1">
                    {spaces.map((space) => {
                        const isCurrent = space.name === currentSpace
                        return (
                            <LemonButton
                                key={space.path}
                                type="tertiary"
                                fullWidth
                                icon={<AnalyticsSpaceGlyph name={space.name} size="md" />}
                                loading={sharing}
                                disabledReason={isCurrent ? 'Already here' : sharing ? 'Working…' : undefined}
                                onClick={() => shareToSpace(space)}
                                data-attr="analytics-share-to-space"
                            >
                                <span className="flex flex-col items-start">
                                    <span>{space.name}</span>
                                    <span className="text-xs text-secondary">
                                        {isCurrent
                                            ? 'Current collection'
                                            : space.total === 0
                                              ? 'Empty'
                                              : `${space.total} ${space.total === 1 ? 'item' : 'items'}`}
                                    </span>
                                </span>
                            </LemonButton>
                        )
                    })}
                    {moving && (
                        <LemonButton
                            type="tertiary"
                            fullWidth
                            loading={sharing}
                            onClick={() => shareToSpace(null)}
                            data-attr="analytics-share-make-personal"
                        >
                            <span className="flex flex-col items-start">
                                <span>No collection</span>
                                <span className="text-xs text-secondary">
                                    Takes it out of every collection. It stays in View all.
                                </span>
                            </span>
                        </LemonButton>
                    )}
                </div>
            )}
        </LemonModal>
    )
}

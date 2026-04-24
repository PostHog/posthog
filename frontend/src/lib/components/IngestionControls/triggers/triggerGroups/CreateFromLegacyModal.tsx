import { LemonBanner, LemonButton, LemonModal, LemonSnack, LemonTag } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils'

import { SessionRecordingTriggerGroup } from '~/lib/components/IngestionControls/types'

export function CreateFromLegacyModal({
    isOpen,
    onClose,
    onConfirm,
    previewGroups,
    isCreating,
}: {
    isOpen: boolean
    onClose: () => void
    onConfirm: () => void
    previewGroups: SessionRecordingTriggerGroup[]
    isCreating: boolean
}): JSX.Element {
    const willCreateMultipleGroups = previewGroups.length > 1

    return (
        <LemonModal isOpen={isOpen} onClose={onClose} title="Create trigger groups from legacy settings">
            <div className="space-y-4">
                <p className="text-sm text-muted">
                    This will create {pluralize(previewGroups.length, 'trigger group', 'trigger groups')} based on your
                    current legacy trigger settings. You can edit these groups after creating them.
                </p>

                {willCreateMultipleGroups && (
                    <LemonBanner type="info">
                        <strong>Why 2 groups?</strong>
                        <p className="mt-1">
                            Your legacy triggers use "ANY" match type, including sampling. This means recording starts
                            if <strong>any</strong> trigger matches <strong>OR</strong> the session was sampled. To have
                            functionally equivalent trigger groups, this requires 2 groups: one to always start
                            recording when the conditions are met, and one to record the sampled amount of all sessions.
                        </p>
                    </LemonBanner>
                )}

                <div className="space-y-2">
                    {previewGroups.map((group, index) => {
                        const hasConditions =
                            (group.conditions.urls && group.conditions.urls.length > 0) ||
                            (group.conditions.events && group.conditions.events.length > 0) ||
                            !!group.conditions.flag
                        const matchType = group.conditions.matchType === 'any' ? 'any' : 'all'

                        return (
                            <div key={index} className="border rounded p-3 bg-surface-primary">
                                {/* Header: Name and Sample Rate */}
                                <div className="flex items-center justify-between mb-3">
                                    <h3 className="mb-0">{group.name}</h3>
                                    <div className="text-right">
                                        <div className="text-xl font-semibold leading-none">
                                            {(group.sampleRate * 100).toFixed(0)}%
                                        </div>
                                        <div className="text-xs text-muted">sample rate</div>
                                    </div>
                                </div>

                                {/* Match type description */}
                                <div className="mb-3">
                                    <span className="text-sm">
                                        {hasConditions ? (
                                            <>
                                                Match <b>sessions</b> against{' '}
                                                <LemonTag type="success" className="uppercase">
                                                    {matchType}
                                                </LemonTag>{' '}
                                                criteria
                                            </>
                                        ) : (
                                            <>
                                                Trigger group will match{' '}
                                                <LemonTag type="success" size="medium">
                                                    all sessions
                                                </LemonTag>
                                            </>
                                        )}
                                    </span>
                                </div>

                                {/* Conditions */}
                                <div className="space-y-2 text-sm">
                                    {group.conditions.urls && group.conditions.urls.length > 0 && (
                                        <div className="flex items-center gap-2 flex-wrap">
                                            <span className="text-muted">User has visited URL matching pattern</span>
                                            {group.conditions.urls.map((u) => (
                                                <LemonSnack key={u.url}>{u.url}</LemonSnack>
                                            ))}
                                        </div>
                                    )}
                                    {group.conditions.events && group.conditions.events.length > 0 && (
                                        <div className="flex items-center gap-2 flex-wrap">
                                            <span className="text-muted">Event</span>
                                            {group.conditions.events.map((event) => {
                                                const name = typeof event === 'string' ? event : event.name
                                                return <LemonSnack key={name}>{name}</LemonSnack>
                                            })}
                                            <span className="text-muted">occurred</span>
                                        </div>
                                    )}
                                    {group.conditions.flag && (
                                        <div className="flex items-center gap-2 flex-wrap">
                                            <span className="text-muted">Feature flag</span>
                                            <LemonSnack>
                                                {typeof group.conditions.flag === 'string'
                                                    ? group.conditions.flag
                                                    : group.conditions.flag.key}
                                            </LemonSnack>
                                            <span className="text-muted">is enabled</span>
                                        </div>
                                    )}
                                </div>

                                {/* Minimum duration */}
                                {group.minDurationMs !== undefined && group.minDurationMs > 0 && (
                                    <div className="text-sm text-muted mt-3">
                                        Minimum duration: <b>{group.minDurationMs / 1000}</b> seconds
                                    </div>
                                )}
                            </div>
                        )
                    })}
                </div>

                <div className="flex justify-end gap-2 pt-2 border-t">
                    <LemonButton type="secondary" onClick={onClose} disabled={isCreating}>
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" onClick={onConfirm} loading={isCreating}>
                        Create {pluralize(previewGroups.length, 'group')}
                    </LemonButton>
                </div>
            </div>
        </LemonModal>
    )
}

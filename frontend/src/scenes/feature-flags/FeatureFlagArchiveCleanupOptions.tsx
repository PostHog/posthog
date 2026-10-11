import { useActions, useValues } from 'kea'

import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { CleanupKeepOption } from './featureFlagCleanupKeep'
import { featureFlagCleanupTargetLogic } from './featureFlagCleanupTargetLogic'
import { FlagCleanupPrOptions } from './FlagCleanupPrOptions'

export interface FeatureFlagArchiveCleanupOptionsProps {
    featureFlagId: number
    featureFlagKey: string
    isFlagActive: boolean
    keepOptions: CleanupKeepOption[]
    openCleanupPr: boolean
    onOpenCleanupPrChange: (value: boolean) => void
    keep: string | null
    onKeepChange: (value: string | null) => void
    repository: string | null
    onRepositoryChange: (value: string | null) => void
}

export function FeatureFlagArchiveCleanupOptions({
    featureFlagId,
    featureFlagKey,
    isFlagActive,
    keepOptions,
    openCleanupPr,
    onOpenCleanupPrChange,
    keep,
    onKeepChange,
    repository,
    onRepositoryChange,
}: FeatureFlagArchiveCleanupOptionsProps): JSX.Element {
    const logic = featureFlagCleanupTargetLogic({ featureFlagId })
    const { cleanupTarget, cleanupTargetLoading, cleanupTargetFailed, cleanupTargetError } = useValues(logic)
    const { loadCleanupTarget } = useActions(logic)

    return (
        <div className="space-y-2 mt-4">
            <FlagCleanupPrOptions
                flagKey={featureFlagKey}
                target={cleanupTarget}
                checked={openCleanupPr}
                onCheckedChange={onOpenCleanupPrChange}
                repository={repository}
                onRepositoryChange={onRepositoryChange}
                dataAttrPrefix="feature-flag-archive"
                disabledReason={
                    cleanupTargetLoading || cleanupTarget?.source === 'refreshing'
                        ? 'Checking connected repositories'
                        : cleanupTargetFailed
                          ? cleanupTargetError || 'Could not check connected repositories'
                          : undefined
                }
            >
                <>
                    <div>
                        <div className="font-semibold mb-1">Code to keep</div>
                        <LemonSelect
                            fullWidth
                            value={keep}
                            onChange={onKeepChange}
                            options={keepOptions}
                            placeholder="Choose the code to keep"
                            data-attr="feature-flag-archive-cleanup-keep"
                        />
                    </div>
                    {isFlagActive && keep === 'disabled' && (
                        <div className="text-xs text-muted">
                            Archiving disables the flag now. Users get the code that runs when the flag is off.
                        </div>
                    )}
                </>
            </FlagCleanupPrOptions>
            {(cleanupTargetFailed || cleanupTarget?.source === 'refreshing') && (
                <div className="text-xs text-muted flex items-center gap-1">
                    {cleanupTargetError || 'Connected repositories are being refreshed. Try again in a moment.'}
                    <LemonButton size="xsmall" type="secondary" onClick={() => loadCleanupTarget()}>
                        Try again
                    </LemonButton>
                </div>
            )}
        </div>
    )
}

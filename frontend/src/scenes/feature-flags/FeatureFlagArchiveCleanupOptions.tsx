import { useValues } from 'kea'

import { LemonCheckbox, LemonInputSelect, LemonSelect } from '@posthog/lemon-ui'

import { CleanupKeepOption } from './featureFlagCleanupKeep'
import { featureFlagCleanupTargetLogic } from './featureFlagCleanupTargetLogic'

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
    const { cleanupTarget } = useValues(featureFlagCleanupTargetLogic({ featureFlagId }))
    const needsRepositoryPick = cleanupTarget?.source === 'ambiguous'

    return (
        <div className="space-y-2 mt-4">
            <LemonCheckbox
                checked={openCleanupPr}
                onChange={onOpenCleanupPrChange}
                data-attr="feature-flag-archive-open-cleanup-pr"
                disabledReason={
                    cleanupTarget?.source === 'no_integration' &&
                    'Connect GitHub in your project settings to open cleanup PRs'
                }
                label={
                    <span>
                        Open a draft PR removing <code>{featureFlagKey}</code> from your code
                    </span>
                }
            />
            {openCleanupPr && (
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
                    {cleanupTarget?.repository && (
                        <div className="text-xs text-muted">
                            The PR will be opened in <code>{cleanupTarget.repository}</code>.
                        </div>
                    )}
                    {needsRepositoryPick && (
                        <LemonInputSelect
                            mode="single"
                            value={repository ? [repository] : []}
                            onChange={(repositories) => onRepositoryChange(repositories[0] ?? null)}
                            options={cleanupTarget.candidates.map((candidate) => ({
                                key: candidate,
                                label: candidate,
                            }))}
                            placeholder="Select a repository"
                            data-attr="feature-flag-archive-cleanup-repository"
                        />
                    )}
                    {isFlagActive && (
                        <div className="text-xs text-muted">
                            Archiving disables the flag now. Until the PR is merged and deployed, users get the code
                            that runs when the flag is off.
                        </div>
                    )}
                </>
            )}
        </div>
    )
}

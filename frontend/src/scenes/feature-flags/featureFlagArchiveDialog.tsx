import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useRef, useState } from 'react'

import { LemonButton, LemonDialog } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { pluralize } from 'lib/utils/strings'

import { FeatureFlagType } from '~/types'

import type { FeatureFlagCleanupPrRequestApi } from 'products/feature_flags/frontend/generated/api.schemas'

import { FeatureFlagArchiveCleanupOptions } from './FeatureFlagArchiveCleanupOptions'
import { cleanupKeepToRequest, getCleanupKeepOptions } from './featureFlagCleanupKeep'
import { featureFlagCleanupTargetLogic } from './featureFlagCleanupTargetLogic'

export type FeatureFlagArchivedSource = 'archive-dialog' | 'disable-confirmation'

export function reportFeatureFlagArchived(via: FeatureFlagArchivedSource): void {
    posthog.capture('feature flag archived', { via })
}

function archiveDescription(active: boolean): string {
    return active
        ? 'This flag is currently enabled — archiving will disable it and immediately roll it back from users matching the release conditions. Archived flags are hidden from the flag list, but linked experiments and surveys keep their data.'
        : 'Archived flags are hidden from the flag list, but linked experiments and surveys keep their data. You can unarchive it at any time.'
}

function FeatureFlagArchiveDialogContent({
    featureFlag,
    onArchive,
    closeDialog,
}: {
    featureFlag: Pick<FeatureFlagType, 'id' | 'key' | 'active' | 'filters'>
    onArchive: (cleanupPr?: FeatureFlagCleanupPrRequestApi) => void
    closeDialog: () => void
}): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const [openCleanupPr, setOpenCleanupPr] = useState<boolean>(false)
    const [keep, setKeep] = useState<string | null>(null)
    const [repository, setRepository] = useState<string | null>(null)
    const submitted = useRef(false)
    const [submitting, setSubmitting] = useState(false)

    // The cleanup PR runs as a PostHog Desktop task, so the user needs Code access.
    const cleanupAvailable = !!featureFlags[FEATURE_FLAGS.TASKS] && featureFlag.id != null
    const { cleanupTarget } = useValues(featureFlagCleanupTargetLogic({ featureFlagId: featureFlag.id ?? 0 }))
    // The checkbox stays locked until the repository lookup answers, so an opt-in always has a target to check.
    const withCleanupPr =
        cleanupAvailable &&
        openCleanupPr &&
        cleanupTarget != null &&
        cleanupTarget.source !== 'no_integration' &&
        cleanupTarget.source !== 'refreshing'
    // With several connected repositories and no default, the backend refuses to guess, so a pick is required.
    const needsRepositoryPick = cleanupTarget?.source === 'ambiguous'

    const archiveDisabledReason = !withCleanupPr
        ? undefined
        : !keep
          ? 'Choose the code to keep'
          : needsRepositoryPick && !repository
            ? 'Select a repository for the cleanup PR'
            : undefined

    return (
        <>
            <p className="mb-0">
                {withCleanupPr && keep && keep !== 'disabled'
                    ? 'The flag keeps its current settings while the cleanup PR is prepared. Archive it after the PR is merged and deployed.'
                    : archiveDescription(featureFlag.active)}
            </p>
            {cleanupAvailable && (
                <FeatureFlagArchiveCleanupOptions
                    featureFlagId={featureFlag.id as number}
                    featureFlagKey={featureFlag.key}
                    isFlagActive={featureFlag.active}
                    keepOptions={getCleanupKeepOptions(featureFlag)}
                    openCleanupPr={openCleanupPr}
                    onOpenCleanupPrChange={setOpenCleanupPr}
                    keep={keep}
                    onKeepChange={setKeep}
                    repository={repository}
                    onRepositoryChange={setRepository}
                />
            )}
            <div className="flex justify-end gap-2 mt-4">
                <LemonButton type="tertiary" size="small" onClick={closeDialog}>
                    Cancel
                </LemonButton>
                <LemonButton
                    type="primary"
                    size="small"
                    data-attr="feature-flag-archive-confirm"
                    disabledReason={archiveDisabledReason}
                    loading={submitting}
                    onClick={() => {
                        if (submitted.current) {
                            return
                        }
                        submitted.current = true
                        setSubmitting(true)
                        closeDialog()
                        onArchive(withCleanupPr && keep ? cleanupKeepToRequest(keep, repository) : undefined)
                    }}
                >
                    {withCleanupPr && keep && keep !== 'disabled' ? 'Start cleanup PR' : 'Archive'}
                </LemonButton>
            </div>
        </>
    )
}

/**
 * Opens the archive confirmation dialog for a feature flag. The warning copy lives here so the
 * detail page and the list share one source of truth — only the confirm callback differs.
 * Unarchiving is immediate at the call site, so it doesn't go through this dialog.
 * `onArchive` receives the cleanup PR request when the user opted in to one.
 */
export function openFeatureFlagArchiveDialog(
    featureFlag: Pick<FeatureFlagType, 'id' | 'key' | 'active' | 'filters'>,
    onArchive: (cleanupPr?: FeatureFlagCleanupPrRequestApi) => void
): void {
    LemonDialog.open({
        title: 'Archive this flag?',
        content: (closeDialog) => (
            <FeatureFlagArchiveDialogContent
                featureFlag={featureFlag}
                onArchive={onArchive}
                closeDialog={closeDialog}
            />
        ),
        primaryButton: null,
        secondaryButton: null,
    })
}

/**
 * Opens the archive confirmation dialog for the flags selected in the list. The copy can't name a
 * single flag's state, so it warns about enabled flags in general.
 */
export function openBulkArchiveFlagsDialog(flagCount: number, onArchive: () => void): void {
    LemonDialog.open({
        title: `Archive ${pluralize(flagCount, 'flag')}?`,
        description:
            'Any of these flags that are still enabled will be disabled and rolled back from users matching their release conditions. Flags that need approval to disable will create a change request instead of archiving. Archived flags are hidden from the flag list, but linked experiments and surveys keep their data. You can unarchive them at any time.',
        primaryButton: {
            children: 'Archive',
            type: 'primary',
            onClick: onArchive,
            size: 'small',
        },
        secondaryButton: {
            children: 'Cancel',
            type: 'tertiary',
            size: 'small',
        },
    })
}

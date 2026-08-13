import posthog from 'posthog-js'

import { LemonDialog } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import { FeatureFlagType } from '~/types'

export type FeatureFlagArchivedSource = 'archive-dialog' | 'disable-confirmation'

export function reportFeatureFlagArchived(via: FeatureFlagArchivedSource): void {
    posthog.capture('feature flag archived', { via })
}

/**
 * Opens the archive confirmation dialog for a feature flag. The warning copy lives here so the
 * detail page and the list share one source of truth — only the confirm callback differs.
 * Unarchiving is immediate at the call site, so it doesn't go through this dialog.
 */
export function openFeatureFlagArchiveDialog(
    featureFlag: Pick<FeatureFlagType, 'active'>,
    onArchive: () => void
): void {
    LemonDialog.open({
        title: 'Archive this flag?',
        description: featureFlag.active
            ? 'This flag is currently enabled — archiving will disable it and immediately roll it back from users matching the release conditions. Archived flags are hidden from the flag list, but linked experiments and surveys keep their data.'
            : 'Archived flags are hidden from the flag list, but linked experiments and surveys keep their data. You can unarchive it at any time.',
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

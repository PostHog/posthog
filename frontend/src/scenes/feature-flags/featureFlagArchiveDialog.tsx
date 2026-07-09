import { LemonDialog } from '@posthog/lemon-ui'

import { FeatureFlagType } from '~/types'

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

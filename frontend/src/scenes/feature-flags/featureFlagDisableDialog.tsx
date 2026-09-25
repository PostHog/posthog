import posthog from 'posthog-js'

import { LemonDialog } from '@posthog/lemon-ui'

export type FeatureFlagDisableDialogSource = 'feature-flags-list' | 'feature-flag-detail'

export type FeatureFlagDisableDialogOption = 'disable' | 'disable_and_archive' | 'cancel'

export function reportFeatureFlagDisableDialogOptionSelected(
    source: FeatureFlagDisableDialogSource,
    option: FeatureFlagDisableDialogOption
): void {
    posthog.capture('feature flag disable confirmation option selected', { source, option })
}

/**
 * Opens the disable confirmation dialog for a feature flag. "Disable only" is the primary action;
 * "Disable and archive" sits alongside it as a destructive secondary, so the more destructive
 * option reads as destructive and isn't the default click.
 */
export function openFeatureFlagDisableDialog({
    source,
    onDisable,
    onDisableAndArchive,
}: {
    source: FeatureFlagDisableDialogSource
    onDisable: () => void
    onDisableAndArchive: () => void
}): void {
    posthog.capture('feature flag disable confirmation shown', { source })

    const selectDisable = (): void => {
        reportFeatureFlagDisableDialogOptionSelected(source, 'disable')
        onDisable()
    }
    const selectCancel = (): void => reportFeatureFlagDisableDialogOptionSelected(source, 'cancel')
    const selectDisableAndArchive = (): void => {
        reportFeatureFlagDisableDialogOptionSelected(source, 'disable_and_archive')
        onDisableAndArchive()
    }

    LemonDialog.open({
        title: 'Disable this flag?',
        description:
            'This flag will be immediately rolled back from the users matching the release conditions. Done with it for good? Archive it too: archived flags are hidden from the flag list, but linked experiments and surveys keep their data.',
        primaryButton: {
            children: 'Disable only',
            type: 'primary',
            size: 'small',
            onClick: selectDisable,
        },
        secondaryButton: {
            children: 'Disable and archive',
            type: 'secondary',
            status: 'danger',
            size: 'small',
            onClick: selectDisableAndArchive,
        },
        tertiaryButton: {
            children: 'Cancel',
            type: 'tertiary',
            size: 'small',
            onClick: selectCancel,
        },
    })
}

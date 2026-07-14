import posthog from 'posthog-js'

import { LemonDialog } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic as enabledFeaturesLogic } from 'lib/logic/featureFlagLogic'

export type FeatureFlagDisableDialogSource = 'feature-flags-list' | 'feature-flag-detail'

export type FeatureFlagDisableDialogOption = 'disable' | 'disable_and_archive' | 'cancel'

export function reportFeatureFlagDisableDialogOptionSelected(
    source: FeatureFlagDisableDialogSource,
    option: FeatureFlagDisableDialogOption
): void {
    posthog.capture('feature flag disable confirmation option selected', { source, option })
}

/**
 * Opens the disable confirmation dialog for a feature flag. The test variant of the
 * disable-and-archive experiment gets "Disable and archive" as the primary CTA alongside a
 * "Disable only" option; control keeps each caller's pre-existing dialog. The experiment flag is
 * read here rather than at render so the exposure lines up with the dialog actually opening.
 */
export function openFeatureFlagDisableDialog({
    source,
    onDisable,
    onDisableAndArchive,
    openControlDialog,
}: {
    source: FeatureFlagDisableDialogSource
    onDisable: () => void
    onDisableAndArchive: () => void
    /** The pre-experiment dialog, shown to the control variant */
    openControlDialog: () => void
}): void {
    const inTestVariant =
        enabledFeaturesLogic.findMounted()?.values.featureFlags[
            FEATURE_FLAGS.FEATURE_FLAG_DISABLE_AND_ARCHIVE_EXPERIMENT
        ] === 'test'

    posthog.capture('feature flag disable confirmation shown', { source })

    if (!inTestVariant) {
        openControlDialog()
        return
    }

    LemonDialog.open({
        title: 'Disable this flag?',
        description:
            'This flag will be immediately rolled back from the users matching the release conditions. Done with it for good? Archive it too: archived flags are hidden from the flag list, but linked experiments and surveys keep their data.',
        primaryButton: {
            children: 'Disable and archive',
            type: 'primary',
            size: 'small',
            onClick: () => {
                reportFeatureFlagDisableDialogOptionSelected(source, 'disable_and_archive')
                posthog.capture('feature flag archived', { via: 'disable-confirmation' })
                onDisableAndArchive()
            },
        },
        secondaryButton: {
            children: 'Disable only',
            type: 'secondary',
            size: 'small',
            onClick: () => {
                reportFeatureFlagDisableDialogOptionSelected(source, 'disable')
                onDisable()
            },
        },
        tertiaryButton: {
            children: 'Cancel',
            type: 'tertiary',
            size: 'small',
            onClick: () => {
                reportFeatureFlagDisableDialogOptionSelected(source, 'cancel')
            },
        },
    })
}

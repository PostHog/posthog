import { useActions, useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import type { VariantColumn } from '../../ExperimentForm/VariantsPanelCreateFeatureFlag'
import { VariantScreenshotEditor } from '../../ExperimentView/VariantScreenshot'
import { experimentWizardLogic } from '../experimentWizardLogic'

/**
 * Stored in the draft's `parameters`, where the experiment's Variants tab reads them after saving. Only the `test` arm
 * of EXPERIMENT_WIZARD_VARIANT_DETAILS gets them; the flag is read here, so exposure is recorded on the variants step.
 */
export function useVariantDetailsColumns(): VariantColumn[] {
    const { experiment } = useValues(experimentWizardLogic)
    const { setVariantNote, setVariantScreenshots, setVariantUploadPending } = useActions(experimentWizardLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    if (featureFlags[FEATURE_FLAGS.EXPERIMENT_WIZARD_VARIANT_DETAILS] !== 'test') {
        return []
    }

    const notes = experiment.parameters?.variant_notes ?? {}
    const screenshots = experiment.parameters?.variant_screenshot_media_ids ?? {}

    // Both are keyed by variant key, so there's nowhere to store them until the variant has one
    const hasKey = (key: string): boolean => key.trim() !== ''
    // Own properties only: a variant key such as `constructor` would otherwise read an inherited function
    const noteFor = (key: string): string | undefined => (Object.hasOwn(notes, key) ? notes[key] : undefined)
    const screenshotsFor = (key: string): string[] => (Object.hasOwn(screenshots, key) ? screenshots[key] : [])

    return [
        {
            key: 'screenshot',
            title: 'Screenshot',
            menuLabel: 'Add screenshot',
            hasValue: ({ key }) => screenshotsFor(key).length > 0,
            isAvailable: ({ key }) => hasKey(key),
            render: ({ key }) =>
                hasKey(key) ? (
                    <VariantScreenshotEditor
                        mediaIds={screenshotsFor(key)}
                        onChange={(mediaIds) => setVariantScreenshots(key, mediaIds)}
                        viewerTitle={<span className="font-semibold">{key}</span>}
                        size="small"
                        uploadTarget={key}
                        onUploadingChange={(uploading) => setVariantUploadPending(key, uploading)}
                    />
                ) : null,
        },
        {
            key: 'notes',
            title: 'Notes',
            menuLabel: 'Add note',
            hasValue: ({ key }) => !!noteFor(key)?.trim(),
            isAvailable: ({ key }) => hasKey(key),
            className: 'w-1/3',
            render: ({ key }) =>
                hasKey(key) ? (
                    <LemonTextArea
                        placeholder="What's different in this variant?"
                        value={noteFor(key) ?? ''}
                        onChange={(value) => setVariantNote(key, value)}
                        // LemonTextArea puts className on its wrapper too, so size only the textarea
                        minRows={1}
                        className="[&.LemonTextArea]:!min-h-[calc(2.125rem+1px)] [&.LemonTextArea]:!py-[7px]"
                        data-attr="experiment-wizard-variant-notes"
                    />
                ) : null,
        },
    ]
}

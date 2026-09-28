import { useActions, useValues } from 'kea'

import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'

import type { Experiment } from '~/types'

import type { VariantColumn } from '../../ExperimentForm/VariantsPanelCreateFeatureFlag'
import { VariantScreenshotEditor } from '../../ExperimentView/VariantScreenshot'
import { experimentWizardLogic } from '../experimentWizardLogic'

/**
 * Screenshot and Notes columns for the wizard's variants table, matching the experiment's Variants tab.
 * Both are optional. They're stored on the draft's `parameters`, keyed by variant key, which is where the
 * Variants tab reads and edits them after saving.
 */
export function useVariantDetailsColumns(): VariantColumn[] {
    const { experiment } = useValues(experimentWizardLogic)
    const { setExperimentValue } = useActions(experimentWizardLogic)

    const notes = experiment.parameters?.variant_notes ?? {}
    const screenshots = experiment.parameters?.variant_screenshot_media_ids ?? {}

    const updateParameters = (update: Partial<Experiment['parameters']>): void => {
        setExperimentValue('parameters', { ...experiment.parameters, ...update })
    }

    // Both are keyed by variant key, so there's nowhere to store them until the variant has one
    const hasKey = (key: string): boolean => key.trim() !== ''

    return [
        {
            key: 'screenshot',
            title: 'Screenshot',
            menuLabel: 'Add screenshot',
            hasValue: ({ key }) => (screenshots[key]?.length ?? 0) > 0,
            isAvailable: ({ key }) => hasKey(key),
            render: ({ key }) =>
                hasKey(key) ? (
                    <VariantScreenshotEditor
                        mediaIds={screenshots[key] ?? []}
                        onChange={(mediaIds) =>
                            updateParameters({ variant_screenshot_media_ids: { ...screenshots, [key]: mediaIds } })
                        }
                        viewerTitle={<span className="font-semibold">{key}</span>}
                        size="small"
                    />
                ) : null,
        },
        {
            key: 'notes',
            title: 'Notes',
            menuLabel: 'Add note',
            hasValue: ({ key }) => !!notes[key]?.trim(),
            isAvailable: ({ key }) => hasKey(key),
            className: 'w-1/3',
            render: ({ key }) =>
                hasKey(key) ? (
                    <LemonTextArea
                        placeholder="What's different in this variant?"
                        value={notes[key] ?? ''}
                        onChange={(value) => updateParameters({ variant_notes: { ...notes, [key]: value } })}
                        // One row, matching the variant key input's height. LemonTextArea puts className on both
                        // its bordered wrapper and the textarea, so scope the sizing to the textarea only.
                        // It grows as the user types.
                        minRows={1}
                        className="[&.LemonTextArea]:!min-h-[calc(2.125rem+1px)] [&.LemonTextArea]:!py-[7px]"
                        data-attr="experiment-wizard-variant-notes"
                    />
                ) : null,
        },
    ]
}

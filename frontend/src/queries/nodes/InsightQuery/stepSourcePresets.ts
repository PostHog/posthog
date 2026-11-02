import { PathsV2StepSource } from '~/queries/schema/schema-general'

export interface StepSourcePreset {
    key: 'pageViews' | 'screenViews'
    label: string
    stepSources: PathsV2StepSource[]
}

/** One-click step source configurations, replacing v1's checkbox event-type buckets. */
export const STEP_SOURCE_PRESETS: Record<StepSourcePreset['key'], StepSourcePreset> = {
    pageViews: {
        key: 'pageViews',
        label: 'Page views',
        stepSources: [{ event: '$pageview', namingProperty: '$pathname' }],
    },
    screenViews: {
        key: 'screenViews',
        label: 'Screen views',
        stepSources: [{ event: '$screen', namingProperty: '$screen_name' }],
    },
}

/** What the runner defaults absent step sources to: the page views preset. */
export const DEFAULT_STEP_SOURCES = STEP_SOURCE_PRESETS.pageViews.stepSources

/** The preset matching the given step sources, or null when they were customized. */
export function presetForStepSources(stepSources: PathsV2StepSource[] | undefined): StepSourcePreset | null {
    if (!stepSources) {
        // The runner defaults absent step sources to the page views preset.
        return STEP_SOURCE_PRESETS.pageViews
    }
    for (const preset of Object.values(STEP_SOURCE_PRESETS)) {
        if (
            stepSources.length === preset.stepSources.length &&
            preset.stepSources.every(
                (source, index) =>
                    stepSources[index].event === source.event &&
                    (stepSources[index].namingProperty ?? null) === (source.namingProperty ?? null)
            )
        ) {
            return preset
        }
    }
    return null
}

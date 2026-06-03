import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'

import { IconArrowLeft, IconInfo } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonSkeleton, Spinner, Tooltip } from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicStringPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { autoresearchNewLogic } from './autoresearchNewLogic'

export const scene: SceneExport = {
    component: AutoresearchNewScene,
    logic: autoresearchNewLogic,
}

function formatPercent(value: number | null | undefined): string {
    if (value === null || value === undefined) {
        return '—'
    }
    return `${(value * 100).toFixed(2)}%`
}

function formatNumber(value: number | null | undefined): string {
    if (value === null || value === undefined) {
        return '—'
    }
    return value.toLocaleString()
}

function ValidationPanel(): JSX.Element {
    const { validation, validationLoading } = useValues(autoresearchNewLogic)

    if (!validation && !validationLoading) {
        return (
            <div className="border rounded p-4 bg-bg-light text-muted text-sm">
                Pick a target event to see live training estimates.
            </div>
        )
    }

    return (
        <div className="border rounded p-4 flex flex-col gap-3">
            <div className="flex items-center justify-between">
                <h3 className="text-base font-semibold mb-0">Live estimate</h3>
                {validationLoading && <Spinner className="text-sm" />}
            </div>

            {validation ? (
                <>
                    <div className="grid grid-cols-2 gap-2 text-sm">
                        <div>
                            <div className="text-muted">Training rows</div>
                            <div className="font-mono">{formatNumber(validation.estimated_training_rows)}</div>
                        </div>
                        <div>
                            <div className="text-muted">Prediction users</div>
                            <div className="font-mono">{formatNumber(validation.inference_population_size)}</div>
                        </div>
                        <div>
                            <div className="text-muted">Positives</div>
                            <div className="font-mono">{formatNumber(validation.positive_count)}</div>
                        </div>
                        <div>
                            <div className="text-muted">Negatives</div>
                            <div className="font-mono">{formatNumber(validation.negative_count)}</div>
                        </div>
                        <div className="col-span-2">
                            <div className="text-muted flex items-center gap-1">
                                Base rate
                                <Tooltip
                                    title={
                                        <span>
                                            For each user in the training population we pick a random reference point in
                                            their history and check whether the target event fired in the following
                                            "Prediction horizon" days. Base rate is the fraction labeled positive — the
                                            conversion rate the model is trained to predict.
                                            <br />
                                            <br />
                                            Computed from a sample of up to 5,000 users for speed; the sampled rate is
                                            an unbiased estimate of what the trainer sees unsampled.
                                        </span>
                                    }
                                >
                                    <IconInfo className="text-sm cursor-help" />
                                </Tooltip>
                            </div>
                            <div className="font-mono">{formatPercent(validation.base_rate)}</div>
                        </div>
                    </div>

                    {validation.warnings.length > 0 && (
                        <div className="flex flex-col gap-2 mt-2">
                            {validation.warnings.map((w, i) => (
                                <LemonBanner
                                    key={`${w.code}-${i}`}
                                    type={
                                        w.severity === 'error' ? 'error' : w.severity === 'warning' ? 'warning' : 'info'
                                    }
                                >
                                    <span className="font-semibold mr-2">{w.code}</span>
                                    {w.message}
                                </LemonBanner>
                            ))}
                        </div>
                    )}

                    {validation.error && (
                        <LemonBanner type="error">Validation failed to run: {validation.error}</LemonBanner>
                    )}
                </>
            ) : (
                <>
                    <LemonSkeleton className="h-4 w-full" />
                    <LemonSkeleton className="h-4 w-3/4" />
                    <LemonSkeleton className="h-4 w-1/2" />
                </>
            )}
        </div>
    )
}

export function AutoresearchNewScene(): JSX.Element {
    const { validation, isNewPipelineSubmitting } = useValues(autoresearchNewLogic)
    const { submitNewPipeline } = useActions(autoresearchNewLogic)

    const blockingError = validation?.warnings.some((w) => w.severity === 'error') ?? false

    return (
        <SceneContent>
            <div className="mb-2">
                <LemonButton type="tertiary" size="small" icon={<IconArrowLeft />} to={urls.autoresearch()}>
                    Back to models
                </LemonButton>
            </div>
            <SceneTitleSection
                name="New model"
                description="Define a target event, horizon, and population. Autoresearch will train models to predict it."
                resourceType={{ type: 'experiment' }}
            />

            <div className="grid grid-cols-1 lg:grid-cols-[1fr_360px] gap-6 items-start">
                <Form
                    logic={autoresearchNewLogic}
                    formKey="newPipeline"
                    className="flex flex-col gap-4 border rounded p-4"
                >
                    <LemonField name="name" label="Name">
                        <LemonInput placeholder="e.g. File sharing prediction" autoFocus />
                    </LemonField>

                    <LemonField
                        name="target_event"
                        label="Target event"
                        info="PostHog event to predict, e.g. shared_file or $pageview. Everything else flows from this pick."
                    >
                        {({ value, onChange }) => (
                            <TaxonomicStringPopover
                                groupType={TaxonomicFilterGroupType.Events}
                                value={value}
                                onChange={(picked) => onChange(picked)}
                                placeholder="Search events..."
                                allowClear
                                data-attr="autoresearch-new-target-event"
                            />
                        )}
                    </LemonField>

                    <div className="flex flex-col gap-3 border-t pt-4">
                        <div>
                            <h3 className="text-base font-semibold mb-1">Training</h3>
                            <p className="text-xs text-muted mb-0">What the model learns from.</p>
                        </div>
                        <LemonField
                            name="training_lookback_days"
                            label="Training lookback (days)"
                            info="How far back to pull training examples from. Larger windows give more data but may include stale behavior. Default: 180 days."
                        >
                            <LemonInput type="number" min={7} max={730} />
                        </LemonField>
                        <LemonField
                            name="training_population"
                            label="Training population"
                            info="Who the model learns from. Leave empty to include all identified users. Often this is users with enough history to be informative (e.g. signed up, has activity)."
                        >
                            {({ value, onChange }) => (
                                <PropertyFilters
                                    pageKey="autoresearch-new-training-population"
                                    propertyFilters={value ?? []}
                                    onChange={(filters) => onChange(filters)}
                                    taxonomicGroupTypes={[
                                        TaxonomicFilterGroupType.PersonProperties,
                                        TaxonomicFilterGroupType.EventProperties,
                                        TaxonomicFilterGroupType.Cohorts,
                                    ]}
                                    buttonText="Add filter"
                                />
                            )}
                        </LemonField>
                    </div>

                    <div className="flex flex-col gap-3 border-t pt-4">
                        <div>
                            <h3 className="text-base font-semibold mb-1">Prediction</h3>
                            <p className="text-xs text-muted mb-0">What the model predicts, and who it scores.</p>
                        </div>
                        <LemonField
                            name="horizon_days"
                            label="Prediction horizon (days)"
                            info="We will predict whether a user does the target event within this many days. Shorter horizons train and validate faster; longer ones capture slower-moving behaviors."
                        >
                            <LemonInput type="number" min={1} max={365} />
                        </LemonField>
                        <LemonField
                            name="inference_population"
                            label="Prediction population"
                            info="Who the model scores daily. Often a different group from training — e.g. train on signed-up users with history, predict on brand new users. Leave empty to score all identified users."
                        >
                            {({ value, onChange }) => (
                                <PropertyFilters
                                    pageKey="autoresearch-new-inference-population"
                                    propertyFilters={value ?? []}
                                    onChange={(filters) => onChange(filters)}
                                    taxonomicGroupTypes={[
                                        TaxonomicFilterGroupType.PersonProperties,
                                        TaxonomicFilterGroupType.EventProperties,
                                        TaxonomicFilterGroupType.Cohorts,
                                    ]}
                                    buttonText="Add filter"
                                />
                            )}
                        </LemonField>
                    </div>

                    <div className="flex justify-end gap-2 mt-2">
                        <LemonButton type="secondary" onClick={() => router.actions.push(urls.autoresearch())}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            loading={isNewPipelineSubmitting}
                            disabledReason={blockingError ? 'Resolve blocking warnings before creating' : undefined}
                            onClick={() => submitNewPipeline()}
                        >
                            Create pipeline
                        </LemonButton>
                    </div>
                </Form>

                <ValidationPanel />
            </div>
        </SceneContent>
    )
}

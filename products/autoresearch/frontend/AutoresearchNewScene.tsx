import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'

import { IconArrowLeft, IconInfo } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonSkeleton, Spinner, Tooltip } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { autoresearchNewLogic, hasTarget } from './autoresearchNewLogic'
import { AdvancedSettings } from './newModel/AdvancedSettings'
import { DefinitionSentence } from './newModel/DefinitionSentence'
import { TemplateChips } from './newModel/TemplateChips'

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
    const { validation, validationLoading, validationFailed, newPipeline, newPipelineValidationErrors } =
        useValues(autoresearchNewLogic)
    const { runValidate } = useActions(autoresearchNewLogic)
    // The form hides field errors until the first submit, and the validate loader skips invalid day values.
    // So this panel is the only place that says why no estimate appears.
    const dayError = newPipelineValidationErrors.training_lookback_days ?? newPipelineValidationErrors.horizon_days

    if (validationFailed && !validationLoading) {
        return (
            <LemonBanner
                type="error"
                action={{
                    children: 'Retry',
                    onClick: () => runValidate(null),
                    'data-attr': 'autoresearch-new-validate-retry',
                }}
            >
                Couldn't check this model definition. Retry, or change a field to check again.
            </LemonBanner>
        )
    }

    if (dayError) {
        return (
            <div className="border rounded p-4 bg-bg-light text-muted text-sm">
                {dayError}. Fix it to see live training estimates.
            </div>
        )
    }

    if (!validation && !validationLoading && !hasTarget(newPipeline)) {
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
                                            "Prediction horizon" days. Base rate is the fraction labeled positive: the
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
    const isEnabled = useFeatureFlag('AUTORESEARCH')
    const { validation, isNewPipelineSubmitting, resolvedTemplateLoading } = useValues(autoresearchNewLogic)
    const { submitNewPipeline } = useActions(autoresearchNewLogic)

    if (!isEnabled) {
        return <NotFound object="Autoresearch" caption="This feature is not enabled for your project." />
    }

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
                description="Pick a template or describe who to predict, what they will do, and when. Autoresearch trains models to predict it."
                resourceType={{ type: 'experiment' }}
            />

            <div className="grid grid-cols-1 @min-[48rem]/main-content:grid-cols-[1fr_360px] gap-6 items-start">
                <Form
                    logic={autoresearchNewLogic}
                    formKey="newPipeline"
                    className="flex flex-col gap-4 border rounded p-4"
                >
                    <TemplateChips />

                    <DefinitionSentence />

                    <LemonField name="name" label="Name">
                        <LemonInput placeholder="e.g. File sharing prediction" />
                    </LemonField>

                    <AdvancedSettings />

                    <div className="flex justify-end gap-2 mt-2">
                        <LemonButton
                            type="secondary"
                            onClick={() => router.actions.push(urls.autoresearch())}
                            data-attr="autoresearch-new-cancel"
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            loading={isNewPipelineSubmitting}
                            disabledReason={
                                blockingError
                                    ? 'Resolve blocking warnings before creating'
                                    : resolvedTemplateLoading
                                      ? 'Wait for the template to load'
                                      : undefined
                            }
                            onClick={() => submitNewPipeline()}
                            data-attr="autoresearch-new-create"
                        >
                            Create model
                        </LemonButton>
                    </div>
                </Form>

                <ValidationPanel />
            </div>
        </SceneContent>
    )
}

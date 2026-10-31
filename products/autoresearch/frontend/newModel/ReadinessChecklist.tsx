import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconCircleDashed, IconInfo, IconWarning, IconX } from '@posthog/icons'
import { LemonBanner, LemonSkeleton, Spinner, Tooltip } from '@posthog/lemon-ui'

import { Readiness, ReadinessCheck, autoresearchNewLogic, hasTarget } from '../autoresearchNewLogic'
import { ValidationWarningApi } from '../generated/api.schemas'

const WARNING_TEXT_CLASS: Record<ValidationWarningApi['severity'], string> = {
    error: 'text-danger',
    warning: 'text-warning-dark',
    info: 'text-muted',
}

const HEADINGS: Record<Readiness, string> = {
    ready: 'Ready to train',
    warnings: 'Ready, with warnings',
    blocked: "Can't train yet",
}

function CheckIcon({ status }: { status: ReadinessCheck['status'] }): JSX.Element {
    if (status === 'fail') {
        return <IconX className="text-danger text-lg shrink-0" />
    }
    if (status === 'warning') {
        return <IconWarning className="text-warning text-lg shrink-0" />
    }
    if (status === 'skipped') {
        return <IconCircleDashed className="text-muted text-lg shrink-0" />
    }
    return <IconCheckCircle className="text-success text-lg shrink-0" />
}

function CheckRow({ check }: { check: ReadinessCheck }): JSX.Element {
    return (
        <li className="flex gap-2">
            <CheckIcon status={check.status} />
            <div className="flex flex-col gap-1 min-w-0">
                <div className="flex flex-wrap items-center gap-x-2">
                    <span className="font-semibold flex items-center gap-1">
                        {check.label}
                        {check.key === 'positives' && (
                            <Tooltip title="Base rate is the share of the training population that did the target event within the horizon. It is estimated from a sample of up to 5,000 users.">
                                <IconInfo className="text-sm text-muted cursor-help" />
                            </Tooltip>
                        )}
                    </span>
                    <span className="font-mono text-muted">{check.value}</span>
                </div>
                {check.warnings.map((warning, index) => (
                    <div key={`${warning.code}-${index}`} className={WARNING_TEXT_CLASS[warning.severity]}>
                        {warning.message}
                    </div>
                ))}
            </div>
        </li>
    )
}

export function ReadinessChecklist(): JSX.Element {
    const {
        validation,
        validationLoading,
        validationFailed,
        newPipeline,
        newPipelineValidationErrors,
        readiness,
        readinessChecks,
    } = useValues(autoresearchNewLogic)
    const { runValidate } = useActions(autoresearchNewLogic)
    // The form hides field errors until the first submit, and the validate loader skips invalid day values.
    // So this panel is the only place that says why no check appears.
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
                {dayError}. Fix it to check if this model is ready to train.
            </div>
        )
    }

    if (!validation && !validationLoading && !hasTarget(newPipeline)) {
        return (
            <div className="border rounded p-4 bg-bg-light text-muted text-sm">
                Pick a target event to check if this model is ready to train.
            </div>
        )
    }

    return (
        <div className="border rounded p-4 flex flex-col gap-3" data-attr="autoresearch-new-readiness">
            <div className="flex items-center justify-between">
                <h3 className="text-base font-semibold mb-0">
                    {readiness ? HEADINGS[readiness] : 'Checking your data'}
                </h3>
                {validationLoading && <Spinner className="text-sm" />}
            </div>

            {validation ? (
                <>
                    {validation.error && (
                        <LemonBanner
                            type="error"
                            action={{
                                children: 'Retry',
                                onClick: () => runValidate(null),
                                loading: validationLoading,
                                'data-attr': 'autoresearch-new-validate-retry',
                            }}
                        >
                            Couldn't check this model: {validation.error}
                        </LemonBanner>
                    )}
                    {readinessChecks.length > 0 && (
                        <ul className="flex flex-col gap-3 text-sm">
                            {readinessChecks.map((check) => (
                                <CheckRow key={check.key} check={check} />
                            ))}
                        </ul>
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

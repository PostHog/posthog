import equal from 'fast-deep-equal'

import { LemonTag } from 'lib/lemon-ui/LemonTag'

import {
    isExperimentFunnelMetric,
    isExperimentMeanMetric,
    isExperimentRatioMetric,
} from '~/queries/schema/schema-general'
import { ExperimentMetric } from '~/queries/schema/schema-general'
import { getDefaultMetricTitle } from '~/scenes/experiments/MetricsView/shared/utils'

const getOutlierHandlingChanges = (metricBefore: ExperimentMetric, metricAfter: ExperimentMetric): string | null => {
    // bail if it's a metric type change
    if (!isExperimentMeanMetric(metricBefore) || !isExperimentMeanMetric(metricAfter)) {
        return null
    }

    // check if the outlier handling was removed completely
    if (
        metricBefore.upper_bound_percentile &&
        !metricAfter.upper_bound_percentile &&
        metricBefore.lower_bound_percentile &&
        !metricAfter.lower_bound_percentile
    ) {
        return 'removed the outlier handling lower and upper bounds'
    }

    // check if the lower bound was removed
    if (metricBefore.lower_bound_percentile && !metricAfter.lower_bound_percentile) {
        return 'removed the outlier handling lower bound percentile'
    }

    // check if the upper bound was removed
    if (metricBefore.upper_bound_percentile && !metricAfter.upper_bound_percentile) {
        return 'removed the outlier handling upper bound percentile'
    }

    // check if the outlier handling was added completely
    if (
        !metricBefore.upper_bound_percentile &&
        !metricBefore.lower_bound_percentile &&
        metricAfter.upper_bound_percentile &&
        metricAfter.lower_bound_percentile
    ) {
        return `set the outlier handling lower bound percentile to ${metricAfter.lower_bound_percentile} and upper bound percentile to ${metricAfter.upper_bound_percentile}`
    }

    // check if ONLY the lower bound was changed
    if (
        !metricBefore.upper_bound_percentile &&
        metricBefore.lower_bound_percentile &&
        !metricAfter.upper_bound_percentile &&
        metricAfter.lower_bound_percentile
    ) {
        return `set the outlier handling lower bound percentile to ${metricAfter.lower_bound_percentile}`
    }

    // check if ONLY the upper bound was changed
    if (
        metricBefore.upper_bound_percentile &&
        !metricBefore.lower_bound_percentile &&
        metricAfter.upper_bound_percentile &&
        !metricAfter.lower_bound_percentile
    ) {
        return `set the outlier handling upper bound percentile to ${metricAfter.upper_bound_percentile}`
    }

    return null
}

const removeFingerprint = ({ fingerprint, ...metric }: ExperimentMetric): ExperimentMetric => metric

const getRatioChanges = (metricBefore: ExperimentMetric, metricAfter: ExperimentMetric): string | null => {
    // bail if it's a metric type change
    if (!isExperimentRatioMetric(metricBefore) || !isExperimentRatioMetric(metricAfter)) {
        return null
    }

    // check if both numerator and denominator were changed
    if (
        !equal(metricBefore.numerator, metricAfter.numerator) &&
        !equal(metricBefore.denominator, metricAfter.denominator)
    ) {
        return `changed the numerator and denominator`
    }

    // check if the numerator was changed
    if (!equal(metricBefore.numerator, metricAfter.numerator)) {
        return `changed the numerator`
    }

    // check if the denominator was changed
    if (!equal(metricBefore.denominator, metricAfter.denominator)) {
        return `changed the denominator`
    }

    return null
}
export const getMetricChanges = (
    before: ExperimentMetric[],
    after: ExperimentMetric[]
): string | JSX.Element | (string | JSX.Element)[] | null => {
    if (after.length > before.length) {
        return 'added a metric to'
    }
    if (after.length < before.length) {
        return 'removed a metric from'
    }

    /**
     * we need to find the metric that was changed and the value that was changed.
     * we can use the `fingerprint` to identify the metric that was changed.
     * There could only be one metric that was changed.
     */
    const metricAfter = after.find(
        (afterMetric) => !before.some((beforeMetric) => beforeMetric.fingerprint === afterMetric.fingerprint)
    )
    const metricBefore = before.find(
        (beforeMetric) => !after.some((afterMetric) => afterMetric.fingerprint === beforeMetric.fingerprint)
    )

    if (!metricAfter || !metricBefore) {
        return null
    }

    /**
     * there are special cases where the fingerprint is THE only difference between the metrics.
     * we need to handle these cases.
     */
    if (equal(removeFingerprint(metricAfter), removeFingerprint(metricBefore))) {
        return null
    }

    const changes: (string | JSX.Element)[] = []
    // check if the metric type was changed:
    if (metricAfter.metric_type !== metricBefore.metric_type) {
        changes.push(
            <span>
                changed the type from <LemonTag>{metricBefore.metric_type}</LemonTag> to{' '}
                <LemonTag>{metricAfter.metric_type}</LemonTag>
            </span>
        )
    }

    // check if the goal was changed
    if (metricAfter.goal !== metricBefore.goal) {
        changes.push(
            <span>
                set the goal <span className="italic">{metricAfter.goal}</span>
            </span>
        )
    }

    // check if conversion window was removed (reset to default)
    if (metricBefore.conversion_window && !metricAfter.conversion_window) {
        changes.push('set the conversion window to the experiment duration')
    }
    // check if conversion window was added (set to time window)
    if (!metricBefore.conversion_window && metricAfter.conversion_window) {
        changes.push(
            `set the conversion window to ${metricAfter.conversion_window} ${metricAfter.conversion_window_unit}`
        )
    }

    // check if the step order was changed for funnel metrics
    if (
        isExperimentFunnelMetric(metricBefore) &&
        isExperimentFunnelMetric(metricAfter) &&
        metricBefore.funnel_order_type !== metricAfter.funnel_order_type
    ) {
        changes.push(`set the step order to ${metricAfter.funnel_order_type}`)
    }

    // check if the outlier handling was changed for mean metrics
    const outlierHandlingChanges = getOutlierHandlingChanges(metricBefore, metricAfter)
    if (outlierHandlingChanges) {
        changes.push(outlierHandlingChanges)
    }

    // check if the series was changed for funnel metrics
    if (
        isExperimentFunnelMetric(metricBefore) &&
        isExperimentFunnelMetric(metricAfter) &&
        !equal(metricBefore.series, metricAfter.series)
    ) {
        changes.push(`changed the funnel series`)
    }

    // check if the source event was changed for mean metrics
    if (
        isExperimentMeanMetric(metricBefore) &&
        isExperimentMeanMetric(metricAfter) &&
        !equal(metricBefore.source, metricAfter.source)
    ) {
        changes.push(`changed the source event`)
    }

    // check numerator and denominator changes for ratio metrics
    const ratioChanges = getRatioChanges(metricBefore, metricAfter)
    if (ratioChanges) {
        changes.push(ratioChanges)
    }

    /**
     * let's add a way to identify which metric was changed
     * appending the name or series identifier to the last change
     */
    return [
        ...changes.slice(0, -1),
        <>
            {changes.at(-1)}&nbsp;
            <span>
                for the metric <LemonTag>{metricBefore.name || getDefaultMetricTitle(metricBefore)}</LemonTag>
            </span>
        </>,
    ]
}

import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { METRIC_FIELD_COPY, sqlNameFromDisplayName, validateMetricDescription, validateMetricName } from '../common'
import { metricsLogic } from '../metricsLogic'
import { MetricNameField, MetricNameValue } from './MetricNameField'

export interface MetricFromInsightModalProps {
    insightShortId?: string
    insightName?: string
}

function namesFromInsight(insightName: string | undefined): MetricNameValue {
    const displayName = insightName ?? ''
    return { display_name: displayName, name: sqlNameFromDisplayName(displayName) }
}

export function MetricFromInsightModal({ insightShortId, insightName }: MetricFromInsightModalProps): JSX.Element {
    const { metricFromInsightModalOpen, creatingMetricAs, allMetrics } = useValues(metricsLogic)
    const { createMetricFromInsight, closeMetricFromInsightModal } = useActions(metricsLogic)

    const [names, setNames] = useState<MetricNameValue>(() => namesFromInsight(insightName))
    const [description, setDescription] = useState('')
    const [unit, setUnit] = useState('')

    useEffect(() => {
        if (metricFromInsightModalOpen) {
            setNames(namesFromInsight(insightName))
            setDescription('')
            setUnit('')
        }
    }, [metricFromInsightModalOpen, insightName])

    const sqlName = names.name.trim()
    const nameError = names.display_name.trim() ? validateMetricName(sqlName) : 'Name the metric'
    const descriptionError = validateMetricDescription(description)
    const sqlNameTaken = !!sqlName && allMetrics.some((metric) => metric.name === sqlName)

    const metricsFromThisInsight = insightShortId
        ? allMetrics.filter((metric) => metric.source_insight_short_id === insightShortId)
        : []

    const submitDisabledReason = !insightShortId
        ? 'Save the insight first'
        : nameError
          ? nameError
          : !description.trim()
            ? 'Add a description'
            : descriptionError

    const submit = (approve: boolean): void => {
        if (submitDisabledReason || !insightShortId) {
            return
        }
        createMetricFromInsight(
            {
                name: sqlName,
                display_name: names.display_name.trim(),
                description: description.trim(),
                unit: unit.trim(),
                source_insight_short_id: insightShortId,
            },
            approve
        )
    }

    return (
        <LemonModal
            isOpen={metricFromInsightModalOpen}
            onClose={closeMetricFromInsightModal}
            width={560}
            title="Create metric from insight"
        >
            <LemonModal.Content>
                <div className="flex flex-col gap-4">
                    {metricsFromThisInsight.length > 0 && (
                        <div className="flex flex-col gap-1">
                            <span className="text-secondary">Metrics already created from this insight</span>
                            <LemonTable
                                dataSource={metricsFromThisInsight}
                                columns={[
                                    {
                                        title: 'Name',
                                        key: 'name',
                                        render: (_, metric) => (
                                            <Link to={urls.dataCatalogMetric(metric.name)}>
                                                {metric.display_name || metric.name}
                                            </Link>
                                        ),
                                    },
                                ]}
                                size="small"
                                embedded
                            />
                        </div>
                    )}

                    <MetricNameField
                        displayName={names.display_name}
                        sqlName={names.name}
                        onChange={setNames}
                        sqlNameError={names.display_name.trim() ? validateMetricName(sqlName) : undefined}
                        sqlNameTaken={sqlNameTaken}
                        autoFocus
                    />

                    <LemonField.Pure
                        label={METRIC_FIELD_COPY.description.label}
                        error={descriptionError}
                        info="One or two short sentences: what the number is and what it counts."
                    >
                        <LemonInput
                            value={description}
                            onChange={setDescription}
                            placeholder={METRIC_FIELD_COPY.description.placeholder}
                        />
                    </LemonField.Pure>

                    <LemonField.Pure label="Unit (optional)" className="max-w-60">
                        <LemonInput value={unit} onChange={setUnit} placeholder={METRIC_FIELD_COPY.unit.placeholder} />
                    </LemonField.Pure>
                </div>
            </LemonModal.Content>

            <LemonModal.Footer>
                <LemonButton type="tertiary" onClick={closeMetricFromInsightModal} disabled={!!creatingMetricAs}>
                    Cancel
                </LemonButton>
                <LemonButton
                    type="secondary"
                    onClick={() => submit(false)}
                    loading={creatingMetricAs === 'propose'}
                    disabledReason={
                        submitDisabledReason ?? (creatingMetricAs === 'approve' ? 'Saving the metric' : undefined)
                    }
                    data-attr="data-catalog-create-metric-from-insight-proposed"
                >
                    Save as proposed
                </LemonButton>
                <LemonButton
                    type="primary"
                    onClick={() => submit(true)}
                    loading={creatingMetricAs === 'approve'}
                    disabledReason={
                        submitDisabledReason ?? (creatingMetricAs === 'propose' ? 'Saving the metric' : undefined)
                    }
                    data-attr="data-catalog-create-metric-from-insight-submit"
                >
                    Create and approve
                </LemonButton>
            </LemonModal.Footer>
        </LemonModal>
    )
}

import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { Link } from 'lib/lemon-ui/Link'
import { slugify } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { validateMetricDescription, validateMetricName } from '../common'
import { metricsLogic } from '../metricsLogic'

export interface MetricFromInsightModalProps {
    insightShortId?: string
    insightName?: string
}

export function MetricFromInsightModal({ insightShortId, insightName }: MetricFromInsightModalProps): JSX.Element {
    const { metricFromInsightModalOpen, isCreatingMetric, allMetrics } = useValues(metricsLogic)
    const { createMetricFromInsight, closeMetricFromInsightModal } = useActions(metricsLogic)

    const [name, setName] = useState('')
    const [displayName, setDisplayName] = useState('')
    const [description, setDescription] = useState('')

    const prefilledName = useMemo(() => slugify(insightName || '').replace(/-/g, '_'), [insightName])
    const effectiveName = name || prefilledName
    const nameError = validateMetricName(effectiveName)

    const metricsFromThisInsight = insightShortId
        ? allMetrics.filter((metric) => metric.source_insight_short_id === insightShortId)
        : []

    const descriptionError = validateMetricDescription(description)
    const submitDisabledReason = !insightShortId
        ? 'Save the insight first'
        : nameError
          ? nameError
          : !description.trim()
            ? 'Add a description'
            : descriptionError
              ? descriptionError
              : undefined

    const handleClose = (): void => {
        setName('')
        setDisplayName('')
        setDescription('')
        closeMetricFromInsightModal()
    }

    const handleSubmit = (): void => {
        if (submitDisabledReason || !insightShortId) {
            return
        }
        createMetricFromInsight({
            name: effectiveName,
            display_name: displayName.trim(),
            description: description.trim(),
            source_insight_short_id: insightShortId,
        })
    }

    return (
        <LemonModal
            isOpen={metricFromInsightModalOpen}
            onClose={handleClose}
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

                    <LemonField.Pure
                        label="Name"
                        error={effectiveName ? nameError : undefined}
                        info="A unique identifier for the metric, like monthly_active_users."
                    >
                        <LemonInput
                            value={effectiveName}
                            onChange={setName}
                            placeholder="monthly_active_users"
                            autoFocus
                        />
                    </LemonField.Pure>

                    <LemonField.Pure label="Display name">
                        <LemonInput value={displayName} onChange={setDisplayName} placeholder="Monthly active users" />
                    </LemonField.Pure>

                    <LemonField.Pure
                        label="Description"
                        error={descriptionError}
                        info="1-3 sentences: what the metric means and what it serves."
                    >
                        <LemonInput
                            value={description}
                            onChange={setDescription}
                            placeholder="What this metric measures and how to read it"
                        />
                    </LemonField.Pure>
                </div>
            </LemonModal.Content>

            <LemonModal.Footer>
                <LemonButton type="secondary" onClick={handleClose} disabled={isCreatingMetric}>
                    Cancel
                </LemonButton>
                <LemonButton
                    type="primary"
                    onClick={handleSubmit}
                    loading={isCreatingMetric}
                    disabledReason={submitDisabledReason}
                    data-attr="data-catalog-create-metric-from-insight-submit"
                >
                    Create metric
                </LemonButton>
            </LemonModal.Footer>
        </LemonModal>
    )
}

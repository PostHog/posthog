import { useActions, useValues } from 'kea'

import { IconFolder } from '@posthog/icons'
import { LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import type { EvaluationResultApi } from '../../generated/api.schemas'
import { getUnhealthyProviderKey, providerKeyStateIssueDescription } from '../../settings/providerKeyStateUtils'
import { evaluationTypeUsesProviderKey } from '../evaluationCapabilities'
import { llmEvaluationsLogic } from '../llmEvaluationsLogic'
import { ATTENTION_LABELS, describeAttention, methodLabel, outputTypeLabel } from './evaluationOverviewDisplay'
import { evaluationResultDrawerLogic } from './evaluationResultDrawerLogic'
import { evaluationsOverviewLogic } from './evaluationsOverviewLogic'

export function EvaluationResultNameCell({ row }: { row: EvaluationResultApi }): JSX.Element {
    const { configById, timezone } = useValues(evaluationsOverviewLogic)
    const { providerKeys } = useValues(llmEvaluationsLogic)
    const { openDrawer, prefetchDetails } = useActions(evaluationResultDrawerLogic)
    const config = configById.get(row.id)
    const keyIssue =
        config?.enabled && evaluationTypeUsesProviderKey(config.evaluation_type)
            ? getUnhealthyProviderKey(providerKeys, config.model_configuration?.provider_key_id)
            : null
    const type = outputTypeLabel(row)

    return (
        <div className="flex flex-col gap-1 py-1 min-w-0">
            <Link
                onClick={() => openDrawer(row.id)}
                onMouseEnter={() => prefetchDetails(row.id)}
                className="font-semibold break-words"
                data-attr="evaluation-overview-table-name"
            >
                {row.name}
            </Link>
            <div className="flex flex-wrap items-center gap-1">
                {row.directoryName && (
                    <span className="inline-flex items-center gap-0.5 text-xs text-secondary mr-1">
                        <IconFolder />
                        <span>{row.directoryName}</span>
                    </span>
                )}
                <LemonTag size="small">{methodLabel(row)}</LemonTag>
                {type && <LemonTag size="small">{type}</LemonTag>}
                {!(config?.enabled ?? row.enabled) && !row.attentionReasons.includes('errored') && (
                    <LemonTag size="small" type="muted">
                        Disabled
                    </LemonTag>
                )}
                {row.attentionReasons.map((reason) =>
                    reason === 'errored' ? (
                        <Tooltip
                            key={reason}
                            title={`${describeAttention(row, timezone)}. Open the evaluation to fix it.`}
                        >
                            <LemonTag size="small" type="danger">
                                {ATTENTION_LABELS[reason]}
                            </LemonTag>
                        </Tooltip>
                    ) : (
                        <LemonTag key={reason} size="small" type="warning">
                            {ATTENTION_LABELS[reason]}
                        </LemonTag>
                    )
                )}
                {keyIssue && (
                    <Tooltip
                        title={`Paused because API key ${keyIssue.name} ${providerKeyStateIssueDescription(keyIssue.state)}. Open settings to fix.`}
                    >
                        <Link
                            to={urls.settings('project-ai-observability', 'ai-observability-byok')}
                            data-attr="evaluation-overview-table-key-issue"
                        >
                            <LemonTag size="small" type="warning">
                                Key issue
                            </LemonTag>
                        </Link>
                    </Tooltip>
                )}
            </div>
        </div>
    )
}

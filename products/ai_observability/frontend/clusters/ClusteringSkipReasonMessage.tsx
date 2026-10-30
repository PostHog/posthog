import { LemonButton } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { urls } from 'scenes/urls'

import type { ClusteringSkipReasonApi } from '../generated/api.schemas'
import { ClusteringLevel } from './types'

const ITEM_NOUN: Record<ClusteringLevel, string> = {
    trace: 'summarized traces',
    generation: 'summarized generations',
    evaluation: 'evaluations',
}

const OTHER_LEVELS_HINT: Record<ClusteringLevel, string> = {
    trace: 'Try switching to "Generations" or "Evaluations" to see other clusters, or check back later once more data has been collected.',
    generation:
        'Try switching to "Traces" or "Evaluations" to see other clusters, or check back later once more data has been collected.',
    evaluation:
        'Try switching to "Traces" or "Generations" to see other clusters, or check back later once more data has been collected.',
}

export interface ClusteringSkipReasonMessageProps {
    clusteringLevel: ClusteringLevel
    skipReason: ClusteringSkipReasonApi | null
    onManageJobs: () => void
}

export function ClusteringSkipReasonMessage({
    clusteringLevel,
    skipReason,
    onManageJobs,
}: ClusteringSkipReasonMessageProps): JSX.Element {
    if (skipReason?.reason === 'ai_data_processing_not_approved') {
        return (
            <>
                <p className="text-muted max-w-md">
                    Clustering uses external AI services. Your organization has not approved AI data processing, so
                    scheduled clustering skips this project.
                </p>
                <LemonButton
                    type="primary"
                    size="small"
                    to={urls.settings('organization-details', 'organization-ai-consent')}
                    data-attr="clusters-skip-reason-ai-consent"
                >
                    Review AI settings
                </LemonButton>
            </>
        )
    }

    if (skipReason?.reason === 'no_enabled_job') {
        return (
            <>
                <p className="text-muted max-w-md">
                    No {clusteringLevel} clustering job is enabled, so scheduled clustering skips this level. Create or
                    enable a {clusteringLevel} job to start clustering.
                </p>
                <LemonButton
                    type="primary"
                    size="small"
                    onClick={onManageJobs}
                    data-attr="clusters-skip-reason-manage-jobs"
                >
                    Manage jobs
                </LemonButton>
            </>
        )
    }

    if (skipReason?.reason === 'not_enough_items' && skipReason.item_count !== null && skipReason.min_required) {
        const checkedAt = skipReason.checked_at ? ` on ${dayjs(skipReason.checked_at).format('MMM D')}` : ''
        return (
            <p className="text-muted max-w-md">
                The latest scheduled run{checkedAt} found {skipReason.item_count.toLocaleString()}{' '}
                {ITEM_NOUN[clusteringLevel]}. Clustering needs at least {skipReason.min_required.toLocaleString()}, so
                no clusters were made. Clustering starts automatically once this project has enough data.
            </p>
        )
    }

    if (skipReason?.reason === 'not_scheduled') {
        return (
            <p className="text-muted max-w-md">
                Scheduled clustering runs once a day and has not processed this project recently. Check back tomorrow.
            </p>
        )
    }

    return <p className="text-muted max-w-md">{OTHER_LEVELS_HINT[clusteringLevel]}</p>
}

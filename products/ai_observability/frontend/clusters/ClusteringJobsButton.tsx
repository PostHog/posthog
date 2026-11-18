import { useActions, useValues } from 'kea'

import { IconStack } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { clusteringJobsLogic } from './clusteringJobsLogic'
import { ClusteringJobsPanel } from './ClusteringJobsPanel'

export function ClusteringJobsButton(): JSX.Element {
    const { jobs } = useValues(clusteringJobsLogic)
    const { openJobsPanel } = useActions(clusteringJobsLogic)

    return (
        <>
            <LemonButton
                type="secondary"
                size="small"
                icon={<IconStack />}
                onClick={openJobsPanel}
                className="self-start"
                data-attr="clusters-jobs-button"
            >
                {jobs.length ? `Jobs (${jobs.length})` : 'Jobs'}
            </LemonButton>
            <ClusteringJobsPanel />
        </>
    )
}

import { LemonTag } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { Link } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useMemo } from 'react'

import { JobSpec } from '~/types'

import {
    HISTORICAL_EXPORT_JOB_NAME,
    HISTORICAL_EXPORT_JOB_NAME_V2,
    PluginJobConfiguration,
} from './PluginJobConfiguration'

interface PluginJobOptionsProps {
    pluginId: number
    pluginConfigId: number
    capabilities: Record<'jobs' | 'methods' | 'scheduled_tasks', string[] | undefined>
    publicJobs: Record<string, JobSpec>
    onSubmit: () => void
}

export function PluginJobOptions({
    pluginId,
    pluginConfigId,
    capabilities,
    publicJobs,
    onSubmit,
}: PluginJobOptionsProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)

    const jobs = useMemo(() => {
        return (capabilities?.jobs || [])
            .filter((jobName) => jobName in publicJobs)
            .filter((jobName) => {
                // Hide either old or new export depending on the feature flag value
                if (jobName === HISTORICAL_EXPORT_JOB_NAME && featureFlags[FEATURE_FLAGS.HISTORICAL_EXPORTS_V2]) {
                    return false
                } else if (
                    jobName === HISTORICAL_EXPORT_JOB_NAME_V2 &&
                    !featureFlags[FEATURE_FLAGS.HISTORICAL_EXPORTS_V2]
                ) {
                    return false
                }

                return true
            })
    }, [capabilities, publicJobs, featureFlags])

    return (
        <>
            <h3 className="l3 mt-8">
                Jobs
                <LemonTag type="warning" className="uppercase" style={{ verticalAlign: '0.125em', marginLeft: 6 }}>
                    BETA
                </LemonTag>
            </h3>

            {jobs.map((jobName) => (
                <div key={jobName}>
                    {jobName.includes('Export historical events') ? (
                        <i>
                            Currently unavailable, see{' '}
                            <Link to="https://github.com/PostHog/posthog/issues/15997">GitHub issue</Link>
                        </i>
                    ) : (
                        <>
                            <i>{jobName}</i>
                            <PluginJobConfiguration
                                jobName={jobName}
                                jobSpec={publicJobs[jobName]}
                                pluginConfigId={pluginConfigId}
                                pluginId={pluginId}
                                onSubmit={onSubmit}
                            />
                        </>
                    )}
                </div>
            ))}
        </>
    )
}

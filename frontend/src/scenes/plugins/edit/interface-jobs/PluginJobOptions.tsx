import { Tooltip } from 'lib/components/Tooltip'
import { LemonTag } from 'packages/apps-common'
import React from 'react'
import { JobSpec } from '~/types'
import { PluginJobConfiguration } from './PluginJobConfiguration'

interface PluginJobOptionsProps {
    pluginId: number
    pluginConfigId: number
    capabilities: Record<'jobs' | 'methods' | 'scheduled_tasks', string[]>
    publicJobs: Record<string, JobSpec>
}

export function PluginJobOptions({
    pluginId,
    pluginConfigId,
    capabilities,
    publicJobs,
}: PluginJobOptionsProps): JSX.Element {
    return (
        <>
            <h3 className="l3" style={{ marginTop: 32 }}>
                Jobs
                <LemonTag type="warning" style={{ verticalAlign: '0.125em', marginLeft: 6 }}>
                    BETA
                </LemonTag>
            </h3>

            {capabilities.jobs
                .filter((jobName) => jobName in publicJobs)
                .map((jobName) => (
                    <div key={jobName}>
                        {jobName === 'Export historical events' ? (
                            <Tooltip title="Run this app on all historical events ingested until now">
                                <i>Export historical events</i>
                            </Tooltip>
                        ) : (
                            <i>{jobName}</i>
                        )}
                        <PluginJobConfiguration
                            jobName={jobName}
                            jobSpec={publicJobs[jobName]}
                            pluginConfigId={pluginConfigId}
                            pluginId={pluginId}
                        />
                    </div>
                ))}
        </>
    )
}

import { Tooltip } from 'lib/components/Tooltip'
import React from 'react'
import { PluginTypeWithConfig } from '../../types'
import { PluginJobConfiguration } from './PluginJobConfiguration'

interface PluginJobOptionsProps {
    plugin: PluginTypeWithConfig
    pluginConfigId: number
}

export function PluginJobOptions({ plugin, pluginConfigId }: PluginJobOptionsProps): JSX.Element {
    const { capabilities, public_jobs } = plugin

    if (!capabilities || !capabilities.jobs || !public_jobs || public_jobs.length === 0) {
        return <></>
    }

    return (
        <>
            <h3 className="l3" style={{ marginTop: 32 }}>
                Jobs (Beta)
            </h3>

            {capabilities.jobs.map((jobName) => {
                if (!(jobName in public_jobs)) {
                    return
                }
                return (
                    <div key={jobName}>
                        {jobName === 'Export events from the beginning' ? (
                            <Tooltip title="Run this plugin on all historical events ingested until now">
                                <i>Export events from the beginning</i>
                            </Tooltip>
                        ) : (
                            <i>{jobName}</i>
                        )}
                        <PluginJobConfiguration
                            jobName={jobName}
                            jobSpec={public_jobs[jobName]}
                            pluginConfigId={pluginConfigId}
                            pluginId={plugin.id}
                        />
                    </div>
                )
            })}
        </>
    )
}

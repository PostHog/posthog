import React from 'react'
import { PluginTypeWithConfig } from '../../types'
import { PluginJobConfiguration } from './PluginJobConfiguration'

interface PluginJobOptionsProps {
    plugin: PluginTypeWithConfig
    pluginConfigId: number
}

export function PluginJobOptions({ plugin, pluginConfigId }: PluginJobOptionsProps): JSX.Element {
    const { capabilities, public_jobs } = plugin

    if (!capabilities || !capabilities.jobs || !public_jobs) {
        return <></>
    }

    return (
        <>
            <h3 className="l3" style={{ marginTop: 32 }}>
                Jobs
            </h3>

            {capabilities.jobs.map((jobName) => {
                if (!(jobName in public_jobs)) {
                    return
                }
                return (
                    <div key={jobName}>
                        <i>{jobName}</i>
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

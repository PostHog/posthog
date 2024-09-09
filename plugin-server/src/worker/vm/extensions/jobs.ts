import { Hub, PluginConfig, PluginLogEntryType } from '../../../types'

type JobRunner = {
    runAt: (date: Date) => Promise<void>
    runIn: (duration: number, unit: string) => Promise<void>
    runNow: () => Promise<void>
}
type Job = (payload?: any) => JobRunner
type Jobs = Record<string, Job>

const milliseconds = 1
const seconds = 1000 * milliseconds
const minutes = 60 * seconds
const hours = 60 * minutes
const days = 24 * hours
const weeks = 7 * days
const months = 30 * weeks
const quarters = 13 * weeks
const years = 365 * days
const durations: Record<string, number> = {
    milliseconds,
    seconds,
    minutes,
    hours,
    days,
    weeks,
    months,
    quarters,
    years,
}

export function durationToMs(duration: number, unit: string): number {
    unit = `${unit}${unit.endsWith('s') ? '' : 's'}`
    if (typeof durations[unit] === 'undefined') {
        throw new Error(`Unknown time unit: ${unit}`)
    }
    return durations[unit] * duration
}

export function createJobs(server: Hub, pluginConfig: PluginConfig): Jobs {
    // Jobs were fully removed and are now only here for the VM until it is also fully removed
    const runJob = async (type: string) => {
        try {
            throw new Error('Jobs are no longer supported')
        } catch (e) {
            await pluginConfig.instance?.createLogEntry(
                `Failed to enqueue job ${type} with error: ${e.message}`,
                PluginLogEntryType.Error
            )

            throw e
        }
    }

    return new Proxy(
        {},
        {
            get(target, key) {
                return function createTaskRunner(): JobRunner {
                    return {
                        runAt: async function runAt() {
                            await runJob(key.toString())
                        },
                        runIn: async function runIn() {
                            await runJob(key.toString())
                        },
                        runNow: async function runNow() {
                            await runJob(key.toString())
                        },
                    }
                }
            },
        }
    )
}

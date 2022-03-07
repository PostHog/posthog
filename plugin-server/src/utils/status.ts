import { threadId } from 'worker_threads'

import { callerpath } from './caller'

export type StatusMethod = (icon: string, ...message: any[]) => void

export interface StatusBlueprint {
    debug: StatusMethod
    info: StatusMethod
    warn: StatusMethod
    error: StatusMethod
}

// generates logs in the following format:
// 2022-03-07T11:43:11.105Z [info] 👍 ClickHouse (plugin-server/src/utils/status.ts) threadId=MAIN
export class Status implements StatusBlueprint {
    prefixOverride?: string

    constructor(prefixOverride?: string) {
        this.prefixOverride = prefixOverride
    }

    buildMethod(type: keyof StatusBlueprint): StatusMethod {
        return (icon: string, ...message: any[]) => {
            const threadIdentifier = threadId ? threadId.toString().padStart(4, '_') : 'MAIN'
            const tags = `thread=${threadIdentifier}` // currently tags is static but this could change in the future
            const isoTimestamp = new Date().toISOString()
            const logMessage = [...message].filter(Boolean).join(' ')
            const caller = callerpath().split('posthog/')[1]
            const log = `${isoTimestamp} [${type}] ${icon} ${logMessage} (${caller}) ${tags} `
            console[type](log)
        }
    }

    debug = this.buildMethod('debug')
    info = this.buildMethod('info')
    warn = this.buildMethod('warn')
    error = this.buildMethod('error')
}

export const status = new Status()

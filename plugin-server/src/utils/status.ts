import { StructuredLogger } from 'structlog'
import { threadId } from 'worker_threads'

import { determineNodeEnv, NodeEnv } from './env-utils'

export type StatusMethod = (icon: string, ...message: any[]) => void

export interface StatusBlueprint {
    debug: StatusMethod
    info: StatusMethod
    warn: StatusMethod
    error: StatusMethod
}

export class Status implements StatusBlueprint {
    mode?: string
    logger: StructuredLogger

    constructor(mode?: string) {
        this.mode = mode
        const loggerOptions: Record<string, any> = {
            pathStackDepth: 1,
            useLogIdExtension: true,
        }
        if (determineNodeEnv() !== NodeEnv.Production) {
            loggerOptions['logFormat'] = '{message}'
        }
        this.logger = new StructuredLogger(loggerOptions)
    }

    buildMethod(type: keyof StatusBlueprint): StatusMethod {
        return (icon: string, ...message: any[]) => {
            const singleMessage = [...message].filter(Boolean).join(' ')
            const prefix = this.mode ?? (threadId ? threadId.toString().padStart(4, '_') : 'MAIN')
            const logMessage = `(${prefix}) ${icon} ${singleMessage}`
            this.logger[type](logMessage)
        }
    }

    debug = this.buildMethod('debug')
    info = this.buildMethod('info')
    warn = this.buildMethod('warn')
    error = this.buildMethod('error')
}

export const status = new Status()

import { StructuredLogger } from 'structlog'

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
            useThreadTagsExtension: true,
        }
        if (determineNodeEnv() !== NodeEnv.Production) {
            loggerOptions['logFormat'] = '{message}'
        }
        this.logger = new StructuredLogger(loggerOptions)
    }

    buildMethod(type: keyof StatusBlueprint): StatusMethod {
        return (icon: string, ...message: any[]) => {
            const singleMessage = [...message].filter(Boolean).join(' ')
            const logMessage = `${icon} ${singleMessage}`
            this.logger[type](logMessage, { ...(this.mode ? { mode: this.mode } : {}) })
        }
    }

    debug = this.buildMethod('debug')
    info = this.buildMethod('info')
    warn = this.buildMethod('warn')
    error = this.buildMethod('error')
}

export const status = new Status()

import pino from 'pino'
import { threadId } from 'worker_threads'

import { PluginsServerConfig } from '../types'

export type StatusMethod = (icon: string, ...message: any[]) => void

export interface StatusBlueprint {
    debug: StatusMethod
    info: StatusMethod
    warn: StatusMethod
    error: StatusMethod
}

export class Status implements StatusBlueprint {
    mode?: string
    logger: pino.Logger
    prompt: string

    constructor(mode?: string) {
        this.mode = mode
        this.logger = pino({
            // By default pino will log the level number. So we can easily unify
            // the log structure with other parts of the app e.g. the web
            // server, we output the level name rather than the number. This
            // way, e.g. we can easily ingest into Loki and query across
            // workloads for all `error` log levels.
            formatters: {
                level: (label) => {
                    return { level: label }
                },
            },
        })
        this.prompt = 'MAIN'
    }

    buildMethod(type: keyof StatusBlueprint): StatusMethod {
        return (icon: string, ...message: any[]) => {
            const singleMessage = [...message].filter(Boolean).join(' ')
            const prefix = this.mode ?? (threadId ? threadId.toString().padStart(4, '_') : this.prompt)
            const logMessage = `(${prefix}) ${icon} ${singleMessage}`
            this.logger[type](logMessage)
        }
    }

    updatePrompt(pluginServerMode: PluginsServerConfig['PLUGIN_SERVER_MODE']): void {
        this.prompt = promptForMode(pluginServerMode)
    }

    debug = this.buildMethod('debug')
    info = this.buildMethod('info')
    warn = this.buildMethod('warn')
    error = this.buildMethod('error')
}

function promptForMode(mode: PluginsServerConfig['PLUGIN_SERVER_MODE']): string {
    switch (mode) {
        case null:
            return 'MAIN'
        case 'ingestion':
            return 'INGESTION'
        case 'async':
            return 'ASYNC'
    }
}

export const status = new Status()

import pino from 'pino'

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
    transport: any

    constructor(mode?: string) {
        this.mode = mode

        if (process.env.NODE_ENV === 'production') {
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
                level: 'info',
            })
        } else {
            // If we're not in production, we ensure that:
            //
            //  1. we see debug logs
            //  2. logs are pretty printed
            //
            // NOTE: we keep a reference to the transport such that we can call
            // end on it, otherwise Jest will hang on open handles.
            this.transport = pino.transport({
                target: 'pino-pretty',
                options: {
                    sync: true,
                    level: 'debug',
                },
            })
            this.logger = pino({ level: 'debug' }, this.transport)
        }

        this.prompt = 'MAIN'
    }

    close() {
        this.transport?.end()
    }

    buildMethod(type: keyof StatusBlueprint): StatusMethod {
        return (icon: string, message: string, extra: object) => {
            const logMessage = `${icon} ${message}`
            if (extra instanceof Object) {
                this.logger[type]({ ...extra, msg: logMessage })
            } else {
                this.logger[type](logMessage)
            }
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

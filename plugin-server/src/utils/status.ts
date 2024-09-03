import pino from 'pino'

import { defaultConfig } from '../config/config'
import { LogLevel, PluginsServerConfig } from '../types'
import { isProdEnv } from './env-utils'

export type StatusMethod = (icon: string, ...message: any[]) => void

export interface StatusBlueprint {
    debug: StatusMethod
    info: StatusMethod
    warn: StatusMethod
    error: StatusMethod
}

export class Status implements StatusBlueprint {
    mode?: string
    private logger?: pino.Logger
    prompt: string
    transport: any

    constructor(mode?: string) {
        this.mode = mode

        const logLevel: LogLevel = defaultConfig.LOG_LEVEL
        if (isProdEnv()) {
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
                level: logLevel,
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
                    level: logLevel,
                },
            })
            this.logger = pino({ level: logLevel }, this.transport)
        }
        this.prompt = 'MAIN'
    }

    close() {
        this.transport?.end()
        this.logger = undefined
    }

    buildMethod(type: keyof StatusBlueprint): StatusMethod {
        return (icon: string, message: string, extra: object) => {
            const logMessage = `[${this.prompt}] ${icon} ${message}`

            if (!this.logger) {
                throw new Error(`Logger has been closed! Cannot log: ${logMessage}`)
            }
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
    if (mode == null) {
        return 'MAIN'
    }
    return mode.toUpperCase()
}

export const status = new Status()

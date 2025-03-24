import { PluginEvent } from '@posthog/plugin-scaffold'

import { Hub, PluginConfig, PluginLogEntrySource, PluginLogEntryType, PluginMethods } from '../../../types'
import { PluginInstance } from '../lazy'

export class SemverFlattener implements PluginInstance {
    initialize = async () => {}
    failInitialization = async () => {}
    clearRetryTimeoutIfExists = () => {}
    usedImports: Set<string> | undefined
    methods: PluginMethods

    hub: Hub
    config: PluginConfig
    targetProps: string[]

    constructor(hub: Hub, pluginConfig: PluginConfig) {
        this.hub = hub
        this.config = pluginConfig
        this.usedImports = new Set()

        this.targetProps = (this.config.config.properties as string)?.split(',').map((s) => s.trim())
        if (!this.targetProps) {
            this.targetProps = []
        }

        this.methods = {
            processEvent: (event: PluginEvent) => {
                return Promise.resolve(this.flattenSemver(event))
            },
        }
    }

    public getTeardown(): Promise<PluginMethods['teardownPlugin'] | null> {
        return Promise.resolve(null)
    }

    public getPluginMethod<T extends keyof PluginMethods>(method_name: T): Promise<PluginMethods[T] | null> {
        return Promise.resolve(this.methods[method_name] as PluginMethods[T])
    }

    public setupPluginIfNeeded(): Promise<boolean> {
        return Promise.resolve(true)
    }

    public async createLogEntry(message: string, logType = PluginLogEntryType.Info): Promise<void> {
        // TODO - this will be identical across all plugins, so figure out a better place to put it.
        await this.hub.db.queuePluginLogEntry({
            message,
            pluginConfig: this.config,
            source: PluginLogEntrySource.System,
            type: logType,
            instanceId: this.hub.instanceId,
        })
    }

    flattenSemver(event: PluginEvent): PluginEvent {
        if (!event.properties) {
            return event
        }

        for (const target of this.targetProps) {
            const candidate = event.properties[target]

            if (candidate) {
                const { major, minor, patch, preRelease, build } = splitVersion(candidate)
                event.properties[`${target}__major`] = major
                event.properties[`${target}__minor`] = minor
                if (patch !== undefined) {
                    event.properties[`${target}__patch`] = patch
                }
                if (preRelease !== undefined) {
                    event.properties[`${target}__preRelease`] = preRelease
                }
                if (build !== undefined) {
                    event.properties[`${target}__build`] = build
                }
            }
        }

        return event
    }
}

export interface VersionParts {
    major: number
    minor: number
    patch?: number
    preRelease?: string
    build?: string
}

const splitVersion = (candidate: string): VersionParts => {
    const [head, build] = candidate.split('+')
    const [version, ...preRelease] = head.split('-')
    const [major, minor, patch] = version.split('.')
    return {
        major: Number(major),
        minor: Number(minor),
        patch: patch ? Number(patch) : undefined,
        preRelease: preRelease.join('-') || undefined,
        build,
    }
}

export const SEMVER_FLATTENER_CONFIG_SCHEMA = [
    {
        markdown:
            'Processes specified properties to flatten sematic versions. Assumes any property contains a string which matches [the SemVer specification](https://semver.org/#backusnaur-form-grammar-for-valid-semver-versions)',
    },
    {
        key: 'properties',
        name: 'comma separated properties to explode version number from',
        type: 'string' as const,
        hint: 'my_version_number,app_version',
        default: '',
        required: true,
    },
]

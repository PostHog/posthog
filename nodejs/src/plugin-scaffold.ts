/**
 * Legacy types and code from the deprecated @posthog/plugin-scaffold package (v1.4.4).
 * These supported the old plugin system. Do not use in new code.
 */

// --- Runtime code ---

export class RetryError extends Error {
    _attempt: number | undefined
    _maxAttempts: number | undefined

    constructor(message?: string) {
        super(message)
        this.name = 'RetryError'
    }

    get nameWithAttempts(): string {
        return this._attempt && this._maxAttempts
            ? `${this.name} (attempt ${this._attempt}/${this._maxAttempts})`
            : this.name
    }

    toString(): string {
        return this.message ? `${this.nameWithAttempts}: ${this.message}` : this.nameWithAttempts
    }
}

// --- Types ---

export type Properties = Record<string, any>

export interface Element {
    text?: string
    tag_name?: string
    href?: string
    attr_id?: string
    attr_class?: string[]
    nth_child?: number
    nth_of_type?: number
    attributes?: Record<string, any>
    event_id?: number
    order?: number
    group_id?: number
}

export interface PluginPerson {
    uuid: string
    team_id: number
    properties: Properties
    created_at: string
}

// TODO: These types are "Plugin" types which make no sense anymore
// - we should remove them where possible and stick to more purpose built types
export interface PluginEvent {
    distinct_id: string
    ip: string | null
    site_url: string
    team_id: number
    now: string
    event: string
    sent_at?: string
    properties?: Properties
    timestamp?: string
    offset?: number
    $set?: Properties
    $set_once?: Properties
    uuid: string
    person?: PluginPerson
}

export interface ProcessedPluginEvent {
    distinct_id: string
    ip: string | null
    team_id: number
    event: string
    properties: Properties
    timestamp: string
    $set?: Properties
    $set_once?: Properties
    uuid: string
    person?: PluginPerson
    elements?: Element[]
}

export interface CacheOptions {
    jsonSerialize?: boolean
}

export interface CacheExtension {
    set: (key: string, value: unknown, ttlSeconds?: number, options?: CacheOptions) => Promise<void>
    get: (key: string, defaultValue: unknown, options?: CacheOptions) => Promise<unknown>
    incr: (key: string) => Promise<number>
    expire: (key: string, ttlSeconds: number) => Promise<boolean>
    lpush: (key: string, elementOrArray: unknown[]) => Promise<number>
    lrange: (key: string, startIndex: number, endIndex: number) => Promise<string[]>
    llen: (key: string) => Promise<number>
    lpop: (key: string, count: number) => Promise<string[]>
    lrem: (key: string, count: number, elementKey: string) => Promise<number>
}

export interface StorageExtension {
    set: (key: string, value: unknown) => Promise<void>
    get: (key: string, defaultValue: unknown) => Promise<unknown>
    del: (key: string) => Promise<void>
}

export interface PluginAttachment {
    content_type: string
    file_name: string
    contents: any
}

export type PluginInput = {
    config?: Record<string, any>
    attachments?: Record<string, PluginAttachment | undefined>
    global?: Record<string, any>
}

interface BasePluginMeta {
    cache: CacheExtension
    storage: StorageExtension
    config: Record<string, any>
    global: Record<string, any>
    attachments: Record<string, PluginAttachment | undefined>
}

// eslint-disable-next-line @typescript-eslint/ban-types
export interface Meta<Input extends PluginInput = {}> extends BasePluginMeta {
    attachments: Input['attachments'] extends Record<string, PluginAttachment | undefined>
        ? Input['attachments']
        : Record<string, PluginAttachment | undefined>
    config: Input['config'] extends Record<string, any> ? Input['config'] : Record<string, any>
    global: Input['global'] extends Record<string, any> ? Input['global'] : Record<string, any>
}

export type PluginMeta<T> = T extends { __internalMeta?: infer M } ? M : never

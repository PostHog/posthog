import Redis from 'ioredis'

import { PluginsServerConfig } from '../../types'
import { logger } from '../../utils/logger'
import { recordDeduplicationOperation } from './metrics'
import deduplicationScript from './scripts/deduplication.lua'
import deduplicationIdsScript from './scripts/deduplication-ids.lua'

export type DeduplicationCountResult = {
    duplicates: number
    processed: number
}

export type DeduplicationIdsResult = {
    duplicates: Set<string>
    processed: number
}

export interface DeduplicationOptions {
    keys: string[]
    ttl?: number
}

export interface LuaScript {
    sha: string | null
    script: string
}

export class DeduplicationRedis {
    private client: Redis.Redis | null = null
    private scripts: Record<string, LuaScript>
    private defaultTtl: number
    private isDestroyed = false
    private isDisabled = false
    private config: PluginsServerConfig
    private initializationPromise: Promise<void> | null = null
    private prefix: string

    constructor(config: PluginsServerConfig) {
        this.defaultTtl = config.DEDUPLICATION_TTL_SECONDS
        this.config = config
        this.prefix = `dedup:${config.DEDUPLICATION_REDIS_PREFIX}:`
        this.scripts = {
            deduplication: {
                sha: null,
                script: deduplicationScript,
            },
            deduplicationIds: {
                sha: null,
                script: deduplicationIdsScript,
            },
        }
    }

    private async ensureInitialized(): Promise<void> {
        if (this.isDestroyed) {
            throw new Error('DeduplicationRedis has been destroyed')
        }

        if (this.isDisabled) {
            throw new Error('DeduplicationRedis is disabled due to initialization failure')
        }

        if (!this.client) {
            if (!this.initializationPromise) {
                this.initializationPromise = this.initialize()
            }
            await this.initializationPromise
        }
    }

    private async initialize(): Promise<void> {
        try {
            // Create Redis client directly with minimal retries and fast failure
            const redisOptions: Redis.RedisOptions = {
                host: this.config.DEDUPLICATION_REDIS_HOST,
                port: this.config.DEDUPLICATION_REDIS_PORT,
                maxRetriesPerRequest: 1,
                connectTimeout: 2000,
                commandTimeout: 2000,
                lazyConnect: true,
                enableReadyCheck: false,
            }

            this.client = new Redis(redisOptions)

            // Test connection with timeout
            await Promise.race([
                this.client.ping(),
                new Promise((_, reject) => setTimeout(() => reject(new Error('Connection timeout')), 3000)),
            ])

            // Try to load scripts, but don't fail initialization if script loading fails
            try {
                await this.loadAllScripts()
                logger.info('DeduplicationRedis initialized successfully with scripts preloaded')
            } catch (scriptError) {
                logger.warn(
                    'DeduplicationRedis initialized successfully, but script preloading failed - scripts will be loaded on demand',
                    { scriptError }
                )
            }
        } catch (error) {
            logger.warn('Failed to initialize DeduplicationRedis - disabling deduplication', { error })
            this.isDisabled = true

            // Clean up any partial client
            if (this.client) {
                try {
                    this.client.disconnect()
                } catch (disconnectError) {
                    // Ignore disconnect errors
                }
                this.client = null
            }
            // Don't throw - let the system continue without Redis
        }
    }

    private async loadAllScripts(): Promise<void> {
        if (!this.client) {
            throw new Error('Redis client not initialized')
        }

        try {
            for (const [name, script] of Object.entries(this.scripts)) {
                if (!script.sha) {
                    script.sha = await this.client.script('LOAD', script.script)
                    logger.debug(`Script ${name} loaded successfully`, { sha: script.sha })
                }
            }
        } catch (error) {
            logger.error('Failed to load scripts', { error })
            throw error
        }
    }

    private async reloadScript(name: string): Promise<void> {
        if (!this.client) {
            throw new Error('Redis client not initialized')
        }

        const script = this.scripts[name]
        if (!script) {
            throw new Error(`Script ${name} not found`)
        }

        try {
            script.sha = await this.client.script('LOAD', script.script)
            logger.debug(`Script ${name} reloaded successfully`, { sha: script.sha })
        } catch (error) {
            logger.error(`Failed to reload script ${name}`, { error })
            throw error
        }
    }

    async deduplicate(options: DeduplicationOptions): Promise<DeduplicationCountResult> {
        const { keys, ttl = this.defaultTtl } = options
        const startTime = Date.now()

        if (keys.length === 0) {
            return { duplicates: 0, processed: 0 }
        }

        if (this.isDisabled) {
            logger.debug('Redis deduplication is disabled, returning safe defaults')
            const result = { duplicates: 0, processed: keys.length }
            recordDeduplicationOperation('deduplicate', startTime, result.processed, result.duplicates, 'disabled')
            return result
        }

        try {
            await this.ensureInitialized()
            const duplicates = await this.executeDeduplicationScript(keys, ttl)
            const result = {
                duplicates,
                processed: keys.length,
            }
            recordDeduplicationOperation('deduplicate', startTime, result.processed, result.duplicates, 'success')
            return result
        } catch (error) {
            // If destroyed, throw the error instead of returning safe defaults
            if (this.isDestroyed) {
                throw error
            }

            logger.warn('Deduplication failed, returning safe defaults', {
                error,
                keysCount: keys.length,
                scriptSha: this.scripts.deduplication.sha,
            })
            // Return safe defaults instead of throwing
            const result = { duplicates: 0, processed: keys.length }
            recordDeduplicationOperation('deduplicate', startTime, result.processed, result.duplicates, 'error')
            return result
        }
    }

    async deduplicateIds(options: DeduplicationOptions): Promise<DeduplicationIdsResult> {
        const { keys, ttl = this.defaultTtl } = options
        const startTime = Date.now()

        if (keys.length === 0) {
            return { duplicates: new Set(), processed: 0 }
        }

        if (this.isDisabled) {
            logger.debug('Redis deduplication is disabled, returning safe defaults')
            const result = { duplicates: new Set<string>(), processed: keys.length }
            recordDeduplicationOperation(
                'deduplicateIds',
                startTime,
                result.processed,
                result.duplicates.size,
                'disabled'
            )
            return result
        }

        try {
            await this.ensureInitialized()
            const duplicates = await this.executeDeduplicationIdsScript(keys, ttl)
            const result = {
                duplicates,
                processed: keys.length,
            }
            recordDeduplicationOperation(
                'deduplicateIds',
                startTime,
                result.processed,
                result.duplicates.size,
                'success'
            )
            return result
        } catch (error) {
            // If destroyed, throw the error instead of returning safe defaults
            if (this.isDestroyed) {
                throw error
            }

            logger.warn('DeduplicationIds failed, returning safe defaults', {
                error,
                keysCount: keys.length,
                scriptSha: this.scripts.deduplicationIds.sha,
            })
            // Return safe defaults instead of throwing
            const result = { duplicates: new Set<string>(), processed: keys.length }
            recordDeduplicationOperation('deduplicateIds', startTime, result.processed, result.duplicates.size, 'error')
            return result
        }
    }

    prefixKeys(keys: string[]): string[] {
        return keys.map((key) => `${this.prefix}:${key}`)
    }

    private async executeDeduplicationIdsScript(keys: string[], ttl: number): Promise<Set<string>> {
        if (!this.client) {
            throw new Error('Redis client not initialized')
        }

        const script = this.scripts.deduplicationIds

        // Load script if not already loaded
        if (!script.sha) {
            try {
                script.sha = await this.client.script('LOAD', script.script)
                logger.debug(`Script deduplicationIds loaded successfully`, { sha: script.sha })
            } catch (error) {
                logger.error('Failed to load deduplicationIds script', { error })
                throw error
            }
        }

        const prefixedKeys = this.prefixKeys(keys)

        try {
            const result = await this.client.evalsha(script.sha!, prefixedKeys.length, prefixedKeys, ttl)
            return new Set(Array.isArray(result) ? result : [])
        } catch (error) {
            // Handle NOSCRIPT error by reloading the script
            if (error instanceof Error && error.message.includes('NOSCRIPT')) {
                logger.warn('DeduplicationIds script not found, reloading...')
                await this.reloadScript('deduplicationIds')
                const retryResult = await this.client!.evalsha(script.sha!, prefixedKeys.length, prefixedKeys, ttl)
                return new Set(Array.isArray(retryResult) ? retryResult : [])
            }
            throw error
        }
    }

    private async executeDeduplicationScript(keys: string[], ttl: number): Promise<number> {
        if (!this.client) {
            throw new Error('Redis client not initialized')
        }

        const script = this.scripts.deduplication

        // Load script if not already loaded
        if (!script.sha) {
            try {
                script.sha = await this.client.script('LOAD', script.script)
                logger.debug(`Script deduplication loaded successfully`, { sha: script.sha })
            } catch (error) {
                logger.error('Failed to load deduplication script', { error })
                throw error
            }
        }

        const prefixedKeys = this.prefixKeys(keys)

        try {
            const result = await this.client.evalsha(script.sha!, prefixedKeys.length, prefixedKeys, ttl)
            return typeof result === 'number' ? result : parseInt(result as string, 10)
        } catch (error) {
            // Handle NOSCRIPT error by reloading the script
            if (error instanceof Error && error.message.includes('NOSCRIPT')) {
                logger.warn('Deduplication script not found, reloading...')
                await this.reloadScript('deduplication')
                const retryResult = await this.client!.evalsha(script.sha!, prefixedKeys.length, prefixedKeys, ttl)
                return typeof retryResult === 'number' ? retryResult : parseInt(retryResult as string, 10)
            }
            throw error
        }
    }

    async withClient<T>(callback: (client: Redis.Redis) => Promise<T>): Promise<T> {
        if (this.isDisabled) {
            throw new Error('Redis client is disabled - cannot execute callback')
        }

        try {
            await this.ensureInitialized()

            if (!this.client) {
                throw new Error('Redis client not initialized')
            }

            return await callback(this.client)
        } catch (error) {
            logger.error('Error in withClient callback', { error })
            throw error
        }
    }

    async destroy(): Promise<void> {
        if (this.isDestroyed) {
            return
        }

        this.isDestroyed = true

        try {
            if (this.client && !this.isDisabled) {
                await this.client.quit()
            }
        } catch (error) {
            logger.error('Error destroying DeduplicationRedis', { error })
        }
    }

    // Convenience method for direct deduplication
    async deduplicateKeys(keys: string[], ttl?: number): Promise<number> {
        const result = await this.deduplicate({ keys, ttl })
        return result.duplicates
    }

    // Health check method
    async ping(): Promise<string> {
        await this.ensureInitialized()

        if (!this.client) {
            throw new Error('Redis client not initialized')
        }

        return await this.client.ping()
    }

    // List all available scripts
    getAvailableScripts(): string[] {
        return Object.keys(this.scripts)
    }
}

export function createDeduplicationRedis(config: PluginsServerConfig): DeduplicationRedis {
    return new DeduplicationRedis(config)
}

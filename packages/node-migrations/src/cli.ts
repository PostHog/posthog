#!/usr/bin/env node

import { createLogger, serializeError } from '@posthog/node-service'

import { runPostgresMigrations } from './migrations.js'

interface CliOptions {
    serviceName: string
    migrationsDirectory?: string
    advisoryLockMode: 'fail' | 'wait'
}

function parseOptions(args: string[]): CliOptions {
    let serviceName: string | undefined
    let migrationsDirectory: string | undefined
    let advisoryLockMode: 'fail' | 'wait' = 'fail'

    for (let index = 0; index < args.length; index++) {
        const argument = args[index]
        if (argument === '--service') {
            serviceName = args[++index]
        } else if (argument === '--dir') {
            migrationsDirectory = args[++index]
        } else if (argument === '--wait') {
            advisoryLockMode = 'wait'
        } else {
            throw new Error(`Unknown argument: ${argument}`)
        }
    }

    if (!serviceName) {
        throw new Error('--service is required')
    }

    return {
        serviceName,
        advisoryLockMode,
        ...(migrationsDirectory ? { migrationsDirectory } : {}),
    }
}

async function main(): Promise<void> {
    const options = parseOptions(process.argv.slice(2))
    const databaseUrl = process.env.DATABASE_URL
    if (!databaseUrl) {
        throw new Error('DATABASE_URL is required')
    }

    const logger = createLogger({ serviceName: `${options.serviceName}-migrations` })
    try {
        await runPostgresMigrations({
            databaseUrl,
            serviceName: options.serviceName,
            advisoryLockMode: options.advisoryLockMode,
            logger,
            ...(options.migrationsDirectory ? { migrationsDirectory: options.migrationsDirectory } : {}),
        })
        logger.info({ event: 'database.migrations_complete' }, 'Database migrations complete')
    } catch (error) {
        logger.fatal(
            { event: 'database.migrations_failed', error: serializeError(error) },
            'Database migrations failed'
        )
        process.exitCode = 1
    }
}

main().catch((error: unknown) => {
    console.error(error instanceof Error ? error.message : String(error))
    process.exitCode = 1
})

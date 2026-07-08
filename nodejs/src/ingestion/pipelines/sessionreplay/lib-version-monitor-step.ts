import { Message } from 'node-rdkafka'

import { PipelineWarning } from '~/ingestion/framework/pipeline.interface'
import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'

export interface LibVersionMonitorStepInput {
    message: Message
}

/**
 * Creates a step that monitors the posthog-js library version and emits ingestion
 * warnings when the version is too old to support all session recording features.
 *
 * This is a pass-through step - it preserves all input properties and may emit
 * warnings for old library versions (< 1.75.0).
 */
export function createLibVersionMonitorStep<T extends LibVersionMonitorStepInput>(): ProcessingStep<T, T> {
    return function libVersionMonitorStep(input) {
        const { message } = input

        const libVersion = readLibVersionFromHeaders(message.headers)
        const parsedVersion = parseVersion(libVersion)

        if (parsedVersion && parsedVersion.major === 1 && parsedVersion.minor < 75) {
            const warning: PipelineWarning = {
                type: 'replay_lib_version_too_old',
                details: {
                    libVersion,
                    parsedVersion,
                },
                key: libVersion || 'unknown',
            }

            return Promise.resolve(ok(input, [], [warning]))
        }

        return Promise.resolve(ok(input))
    }
}

function readLibVersionFromHeaders(headers: Message['headers']): string | undefined {
    const libVersionHeader = headers?.find((header) => header['lib_version'])?.['lib_version']
    return typeof libVersionHeader === 'string' ? libVersionHeader : libVersionHeader?.toString()
}

function parseVersion(libVersion: string | undefined): { major: number; minor: number } | undefined {
    if (!libVersion || !libVersion.includes('.')) {
        return undefined
    }

    const parts = libVersion.split('.')
    if (parts.length !== 3) {
        return undefined
    }

    const major = parseInt(parts[0], 10)
    const minor = parseInt(parts[1], 10)

    if (isNaN(major) || isNaN(minor)) {
        return undefined
    }

    return { major, minor }
}

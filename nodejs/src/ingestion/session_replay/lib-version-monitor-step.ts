import { ParsedMessageData } from '../../session-recording/kafka/types'
import { logger } from '../../utils/logger'
import { PipelineWarning } from '../pipelines/pipeline.interface'
import { ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export interface LibVersionMonitorStepInput {
    parsedMessage: ParsedMessageData
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
        const { parsedMessage } = input

        const libVersion = readLibVersionFromHeaders(parsedMessage.headers)
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

function readLibVersionFromHeaders(headers: ParsedMessageData['headers']): string | undefined {
    const libVersionHeader = headers?.find((header) => header['lib_version'])?.['lib_version']
    return typeof libVersionHeader === 'string' ? libVersionHeader : libVersionHeader?.toString()
}

function parseVersion(libVersion: string | undefined): { major: number; minor: number } | undefined {
    try {
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
    } catch (e) {
        logger.warn('could_not_read_minor_lib_version', { libVersion })
        return undefined
    }
}

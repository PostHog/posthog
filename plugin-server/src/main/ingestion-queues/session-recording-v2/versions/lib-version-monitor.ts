import { MessageHeader } from 'node-rdkafka'

import { status } from '../../../../utils/status'
import { MessageWithTeam } from '../teams/types'
import { BatchMessageProcessor, CaptureIngestionWarningFn } from '../types'
import { VersionMetrics } from './version-metrics'

export class LibVersionMonitor<TInput> implements BatchMessageProcessor<TInput, MessageWithTeam> {
    constructor(
        private readonly sourceProcessor: BatchMessageProcessor<TInput, MessageWithTeam>,
        private readonly captureWarning: CaptureIngestionWarningFn,
        private readonly metrics: VersionMetrics
    ) {}

    public async parseBatch(messages: TInput[]): Promise<MessageWithTeam[]> {
        const processedMessages = await this.sourceProcessor.parseBatch(messages)

        for (const message of processedMessages) {
            await this.checkLibVersion(message)
        }

        return processedMessages
    }

    private async checkLibVersion(message: MessageWithTeam): Promise<void> {
        const libVersion = this.readLibVersionFromHeaders(message.message.headers)
        const parsedVersion = this.parseVersion(libVersion)

        if (parsedVersion && parsedVersion.major === 1 && parsedVersion.minor < 75) {
            this.metrics.incrementLibVersionWarning()

            await this.captureWarning(
                message.team.teamId,
                'replay_lib_version_too_old',
                {
                    libVersion,
                    parsedVersion,
                },
                { key: libVersion || 'unknown' }
            )
        }
    }

    private readLibVersionFromHeaders(headers: MessageHeader[] | undefined): string | undefined {
        const libVersionHeader = headers?.find((header) => header['lib_version'])?.['lib_version']
        return typeof libVersionHeader === 'string' ? libVersionHeader : libVersionHeader?.toString()
    }

    private parseVersion(libVersion: string | undefined) {
        try {
            let majorString: string | undefined = undefined
            let minorString: string | undefined = undefined
            if (libVersion && libVersion.includes('.')) {
                const splat = libVersion.split('.')
                if (splat.length === 3) {
                    majorString = splat[0]
                    minorString = splat[1]
                }
            }
            const validMajor = majorString && !isNaN(parseInt(majorString))
            const validMinor = minorString && !isNaN(parseInt(minorString))
            return validMajor && validMinor
                ? {
                      major: parseInt(majorString as string),
                      minor: parseInt(minorString as string),
                  }
                : undefined
        } catch (e) {
            status.warn('⚠️', 'could_not_read_minor_lib_version', { libVersion })
            return undefined
        }
    }
}

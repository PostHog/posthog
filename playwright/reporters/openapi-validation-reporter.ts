import fs from 'node:fs'
import path from 'node:path'

import type { FullConfig, FullResult, Reporter, TestCase, TestResult } from '@playwright/test/reporter'

import {
    OPENAPI_VALIDATION_ATTACHMENT_NAME,
    type OpenAPIValidationAttachment,
    isOpenAPIValidationEnabled,
} from '../utils/openapi-validation'

interface AggregatedOpenAPIValidation {
    totalErrorCount: number
    totalAffectedResponses: number
    testCountWithFindings: number
    endpointErrorCounts: Record<string, number>
}

class OpenAPIValidationReporter implements Reporter {
    private readonly aggregation: AggregatedOpenAPIValidation = {
        totalErrorCount: 0,
        totalAffectedResponses: 0,
        testCountWithFindings: 0,
        endpointErrorCounts: {},
    }

    private outputDirectory: string = process.cwd()

    onBegin(config: FullConfig): void {
        this.outputDirectory = config.projects[0]?.outputDir ?? process.cwd()
    }

    async onTestEnd(_test: TestCase, result: TestResult): Promise<void> {
        if (!isOpenAPIValidationEnabled()) {
            return
        }

        for (const attachment of result.attachments) {
            if (attachment.name !== OPENAPI_VALIDATION_ATTACHMENT_NAME) {
                continue
            }

            const payload = await this.readAttachment(attachment)
            if (!payload) {
                continue
            }

            const summary = JSON.parse(payload) as OpenAPIValidationAttachment
            if (summary.totalErrorCount <= 0) {
                continue
            }

            this.aggregation.totalErrorCount += summary.totalErrorCount
            this.aggregation.totalAffectedResponses += summary.affectedResponseCount
            this.aggregation.testCountWithFindings += 1

            for (const endpoint of summary.endpointStats) {
                this.aggregation.endpointErrorCounts[endpoint.url] =
                    (this.aggregation.endpointErrorCounts[endpoint.url] ?? 0) + endpoint.errorCount
            }
        }
    }

    async onEnd(_result: FullResult): Promise<void> {
        if (!isOpenAPIValidationEnabled()) {
            return
        }

        const endpointStats = Object.entries(this.aggregation.endpointErrorCounts)
            .map(([url, errorCount]) => ({ url, errorCount }))
            .sort((a, b) => b.errorCount - a.errorCount)

        const summary = {
            ...this.aggregation,
            endpointStats,
        }

        const summaryPath = path.join(this.outputDirectory, 'openapi-validation-summary.json')
        fs.mkdirSync(this.outputDirectory, { recursive: true })
        fs.writeFileSync(summaryPath, JSON.stringify(summary, null, 2))

        console.log(`\n[openapi-validation] wrote summary: ${summaryPath}`)
        console.log(
            `[openapi-validation] findings=${summary.totalErrorCount} affected_responses=${summary.totalAffectedResponses} tests_with_findings=${summary.testCountWithFindings}`
        )
        if (endpointStats.length > 0) {
            console.log('[openapi-validation] top endpoints:')
            for (const endpoint of endpointStats.slice(0, 10)) {
                console.log(`  - ${endpoint.errorCount} ${endpoint.url}`)
            }
        }
    }

    private async readAttachment(attachment: TestResult['attachments'][number]): Promise<string | null> {
        if (attachment.body) {
            return attachment.body.toString('utf-8')
        }

        if (!attachment.path) {
            return null
        }

        return await fs.promises.readFile(attachment.path, 'utf-8')
    }
}

export default OpenAPIValidationReporter

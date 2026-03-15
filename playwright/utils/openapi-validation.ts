import { Page, Response, TestInfo } from '@playwright/test'

export interface OpenAPIValidationEndpointStat {
    url: string
    errorCount: number
}

export interface OpenAPIValidationAttachment {
    totalErrorCount: number
    affectedResponseCount: number
    endpointStats: OpenAPIValidationEndpointStat[]
}

const OPENAPI_VALIDATION_ATTACHMENT_NAME = 'openapi-validation-summary'
const OPENAPI_VALIDATION_HEADER = 'x-posthog-openapi-validation-errors'

export function isOpenAPIValidationEnabled(): boolean {
    return !!process.env.PLAYWRIGHT_OPENAPI_VALIDATE
}

export function startOpenAPIValidationCollector(page: Page): () => OpenAPIValidationAttachment {
    const endpointErrorCounts = new Map<string, number>()
    let totalErrorCount = 0
    let affectedResponseCount = 0

    const onResponse = (response: Response): void => {
        const headerValue = response.headers()[OPENAPI_VALIDATION_HEADER]
        if (!headerValue) {
            return
        }

        const parsedCount = Number.parseInt(headerValue, 10)
        if (!Number.isFinite(parsedCount) || parsedCount <= 0) {
            return
        }

        let normalizedUrl: string
        try {
            const parsedUrl = new URL(response.url())
            normalizedUrl = `${parsedUrl.pathname}${parsedUrl.search}`
        } catch {
            normalizedUrl = response.url()
        }

        totalErrorCount += parsedCount
        affectedResponseCount += 1
        endpointErrorCounts.set(normalizedUrl, (endpointErrorCounts.get(normalizedUrl) ?? 0) + parsedCount)
    }

    page.on('response', onResponse)

    return (): OpenAPIValidationAttachment => {
        page.off('response', onResponse)

        const endpointStats = [...endpointErrorCounts.entries()]
            .map(([url, errorCount]) => ({ url, errorCount }))
            .sort((a, b) => b.errorCount - a.errorCount)

        return {
            totalErrorCount,
            affectedResponseCount,
            endpointStats,
        }
    }
}

export async function attachOpenAPIValidationSummary(
    testInfo: TestInfo,
    summary: OpenAPIValidationAttachment
): Promise<void> {
    await testInfo.attach(OPENAPI_VALIDATION_ATTACHMENT_NAME, {
        contentType: 'application/json',
        body: Buffer.from(JSON.stringify(summary, null, 2), 'utf-8'),
    })
}

export { OPENAPI_VALIDATION_ATTACHMENT_NAME }

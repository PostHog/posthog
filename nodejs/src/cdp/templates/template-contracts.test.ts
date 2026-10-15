import { HOG_FUNCTION_TEMPLATES_DESTINATIONS, HOG_FUNCTION_TEMPLATES_TRANSFORMATIONS } from '.'

import { ACCESS_TOKEN_PLACEHOLDER } from '~/common/config/constants'
import { parseJSON } from '~/common/utils/json-parse'

import { OutgoingRequest, PipelineRun, TemplateCase, TemplatePipeline, casesFor } from './test/template-pipeline'

type Exemptions = Record<string, string>

const WORKFLOW_ONLY = 'workflow action, needs a workflow invocation to run'

const RUNS_EXEMPTIONS: Exemptions = {
    'template-email': 'needs an email sender integration in its email input',
    'template-posthog-classify': WORKFLOW_ONLY,
    'template-posthog-create-customer-task': WORKFLOW_ONLY,
    'template-posthog-create-task': WORKFLOW_ONLY,
    'template-posthog-run-scout': WORKFLOW_ONLY,
    'template-posthog-send-ticket-message': WORKFLOW_ONLY,
}

const INTEGRATION_EXEMPTIONS: Exemptions = {}

const WELL_FORMED_EXEMPTIONS: Exemptions = {}

const ENCODED_IN_DEBUG_OUTPUT = 'debug output prints the Basic auth header, and masking misses its encoded form'
const ENCODED_IN_ERROR = 'error message quotes the response body, and masking misses the encoded Basic auth form'

const SECRETS_EXEMPTIONS: Exemptions = {
    'template-twilio': ENCODED_IN_DEBUG_OUTPUT,
    'template-accoil > Track Calls': ENCODED_IN_ERROR,
    'template-accoil > Page Calls': ENCODED_IN_ERROR,
    'template-accoil > Screen Calls': ENCODED_IN_ERROR,
    'template-accoil > Identify Calls': ENCODED_IN_ERROR,
    'template-accoil > Group Calls': ENCODED_IN_ERROR,
    'template-appcues > Track Calls': ENCODED_IN_ERROR,
    'template-appcues > Identify Calls': ENCODED_IN_ERROR,
    'template-close': ENCODED_IN_ERROR,
}

const FAILURES_EXEMPTIONS: Exemptions = {}

const DESTINATION_CASES = casesFor(HOG_FUNCTION_TEMPLATES_DESTINATIONS)
const TRANSFORMATION_CASES = casesFor(HOG_FUNCTION_TEMPLATES_TRANSFORMATIONS)

const OK = { status: 200, body: {} }
const REJECTED = { status: 401, body: {}, echoRequest: true }
const CLIENT_ERROR = { status: 400, body: { error: 'Bad request' } }
const SERVER_ERROR = { status: 500, body: { error: 'Internal error' } }

const runsWithoutError = (run: PipelineRun): string[] => [
    ...run.invocationErrors,
    ...(run.result?.error ? [`execution: ${String(run.result.error)}`] : []),
    ...(run.result && !run.result.finished ? ['execution did not finish'] : []),
]

const wireText = (request: OutgoingRequest): string => {
    const basicAuthCredentials = Object.values(request.headers)
        .filter((value) => typeof value === 'string' && value.startsWith('Basic '))
        .map((value) => Buffer.from(value.slice('Basic '.length), 'base64').toString('utf-8'))
    return [request.url, ...Object.values(request.headers), request.body ?? '', ...basicAuthCredentials].join('\n')
}

const integrationCredentialsReachTheWire = (run: PipelineRun): string[] => {
    const wire = run.requests.map(wireText)
    const leakedPlaceholders = wire
        .filter((text) => text.includes(ACCESS_TOKEN_PLACEHOLDER))
        .map(() => 'a request still carries the access token placeholder')
    const carriesCredential = wire.some((text) =>
        run.integrationCredentials.some((credential) => text.includes(credential))
    )
    return [...leakedPlaceholders, ...(carriesCredential ? [] : ['no request carries the integration credential'])]
}

const HTTP_METHODS = ['GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE']
const UNRESOLVED_TEMPLATE = /\{\{|\{(event|person|groups|inputs|project|source)\./
const STRINGIFIED_MISSING_VALUE = /(^|[/=?&:])(undefined|null)($|[/?&#])/

const jsonStringLeaves = (value: unknown): string[] => {
    if (typeof value === 'string') {
        return [value]
    }
    if (value && typeof value === 'object') {
        return Object.values(value).flatMap(jsonStringLeaves)
    }
    return []
}

const requestProblems = (request: OutgoingRequest): string[] => {
    const problems: string[] = []
    const where = `${request.method} ${request.url}`
    let url: URL | undefined
    try {
        url = new URL(request.url)
    } catch {
        problems.push(`${where}: url does not parse`)
    }
    if (url && !['http:', 'https:'].includes(url.protocol)) {
        problems.push(`${where}: url is not http or https`)
    }
    if (url && STRINGIFIED_MISSING_VALUE.test(decodeURIComponent(url.pathname + url.search))) {
        problems.push(`${where}: url carries a stringified undefined or null`)
    }
    if (!HTTP_METHODS.includes(request.method.toUpperCase())) {
        problems.push(`${where}: method ${request.method} is not an HTTP method`)
    }
    for (const [name, value] of Object.entries(request.headers)) {
        if (value === 'undefined' || value === 'null' || /\b(undefined|null)$/.test(String(value))) {
            problems.push(`${where}: header ${name} carries a stringified undefined or null`)
        }
    }
    if (UNRESOLVED_TEMPLATE.test(wireText(request))) {
        problems.push(`${where}: request carries unresolved template syntax`)
    }
    const contentType = Object.entries(request.headers).find(([name]) => name.toLowerCase() === 'content-type')?.[1]
    if (request.body && String(contentType).includes('json')) {
        try {
            const leaves = jsonStringLeaves(parseJSON(request.body))
            if (leaves.some((leaf) => leaf === 'undefined' || leaf === 'null')) {
                problems.push(`${where}: JSON body carries a stringified undefined or null`)
            }
        } catch {
            problems.push(`${where}: JSON body does not parse`)
        }
    }
    return problems
}

const requestsAreWellFormed = (run: PipelineRun): string[] => [
    ...(run.requests.length === 0 ? ['no request was sent'] : []),
    ...run.requests.flatMap(requestProblems),
]

const BASE64_RUN = /[A-Za-z0-9+/]{12,}={0,2}/g

const withDecodedBase64 = (text: string): string =>
    [text, ...(text.match(BASE64_RUN) ?? []).map((run) => Buffer.from(run, 'base64').toString('utf-8'))].join('\n')

const secretsStayOutOfOutput = (run: PipelineRun): string[] => {
    const output = [...run.printedOutput, ...run.invocationErrors, String(run.result?.error ?? '')].map(
        withDecodedBase64
    )
    return run.sensitiveValues
        .filter((secret) => output.some((text) => text.includes(secret)))
        .map((secret) => `output shows the sensitive value ${secret}`)
}

const failureIsVisible = (run: PipelineRun): string[] => {
    const failed = run.result?.error !== undefined || run.invocationErrors.length > 0
    const retrying = run.result?.finished === false && run.result.invocation.queueScheduledAt !== undefined
    return failed || retrying ? [] : ['the invocation ended as a success']
}

const hasSensitiveValues = ({ template }: TemplateCase): boolean =>
    template.inputs_schema.some((schema) => schema.secret || schema.type === 'integration')

const callsFetch = ({ template }: TemplateCase): boolean => /\bfetch\(/.test(template.code)

const hasIntegrationInput = ({ template }: TemplateCase): boolean =>
    template.inputs_schema.some((schema) => schema.type === 'integration')

const expectInvariant = (templateCase: TemplateCase, exemptions: Exemptions, violations: string[]): void => {
    if (templateCase.name in exemptions) {
        // An exempt case that now passes must leave the list, so the list only shrinks.
        expect(violations).not.toEqual([])
    } else {
        expect(violations).toEqual([])
    }
}

describe('template contracts', () => {
    jest.setTimeout(30000)
    let pipeline: TemplatePipeline

    beforeAll(async () => {
        pipeline = await TemplatePipeline.start()
    })

    afterAll(async () => {
        await pipeline.stop()
    })

    it.each(
        Object.keys({
            ...RUNS_EXEMPTIONS,
            ...INTEGRATION_EXEMPTIONS,
            ...WELL_FORMED_EXEMPTIONS,
            ...SECRETS_EXEMPTIONS,
            ...FAILURES_EXEMPTIONS,
        })
    )('exemption %s names a real case', (name) => {
        expect([...DESTINATION_CASES, ...TRANSFORMATION_CASES].map((c) => c.name)).toContain(name)
    })

    describe.each(DESTINATION_CASES.map((c) => [c.name, c] as const))('%s', (_name, templateCase: TemplateCase) => {
        it('runs on a representative event', async () => {
            const run = await pipeline.run(templateCase, OK)

            expectInvariant(templateCase, RUNS_EXEMPTIONS, runsWithoutError(run))
        })

        if (templateCase.name in RUNS_EXEMPTIONS) {
            return
        }

        if (callsFetch(templateCase)) {
            it('sends well-formed requests', async () => {
                const run = await pipeline.run(templateCase, OK)

                expectInvariant(templateCase, WELL_FORMED_EXEMPTIONS, requestsAreWellFormed(run))
            })

            it('reports client and server error responses as a failure or a retry', async () => {
                const runs = [
                    await pipeline.run(templateCase, CLIENT_ERROR),
                    await pipeline.run(templateCase, SERVER_ERROR),
                ]

                expectInvariant(templateCase, FAILURES_EXEMPTIONS, runs.flatMap(failureIsVisible))
            })
        }

        if (hasSensitiveValues(templateCase)) {
            it('keeps sensitive values out of its output, also when a request is rejected', async () => {
                const runs = [
                    await pipeline.run(templateCase, OK, { debug: true }),
                    await pipeline.run(templateCase, REJECTED, { debug: true }),
                ]

                expectInvariant(templateCase, SECRETS_EXEMPTIONS, runs.flatMap(secretsStayOutOfOutput))
            })
        }

        if (hasIntegrationInput(templateCase)) {
            it('sends the integration credential loaded from its connection', async () => {
                const run = await pipeline.run(templateCase, OK)

                expectInvariant(templateCase, INTEGRATION_EXEMPTIONS, integrationCredentialsReachTheWire(run))
            })
        }
    })

    describe.each(TRANSFORMATION_CASES.map((c) => [c.name, c] as const))('%s', (_name, templateCase: TemplateCase) => {
        it('runs on a representative event', async () => {
            const run = await pipeline.run(templateCase, OK)

            expectInvariant(templateCase, RUNS_EXEMPTIONS, runsWithoutError(run))
        })
    })
})

import { HOG_FUNCTION_TEMPLATES_DESTINATIONS, HOG_FUNCTION_TEMPLATES_TRANSFORMATIONS } from '.'

import { getRegisteredAsyncFunctionNames } from '~/cdp/async-function-registry'
import '~/cdp/async-functions'
import { ACCESS_TOKEN_PLACEHOLDER } from '~/common/config/constants'
import { parseJSON } from '~/common/utils/json-parse'

import { OutgoingRequest, PipelineRun, TemplateCase, TemplatePipeline, casesFor } from './test/template-pipeline'

type Exemptions = Record<string, string>

const WORKFLOW_ONLY = 'workflow action, needs a workflow invocation to run'

const RUNS_EXEMPTIONS: Exemptions = {
    'template-email': 'needs an email sender integration in its email input',
    'template-native-push': 'needs a push notification service, and the harness builds no integration_multi input',
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
    ...(run.thrown ? [run.thrown] : []),
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
const STRINGIFIED_MISSING_VALUE = /(^|[/=?&:.])(undefined|null)($|[/?&#.:])/
const UNDEFINED_WORD = /\bundefined\b/

const carriesMissingValue = (text: string): boolean => text === 'null' || UNDEFINED_WORD.test(text)

const decodeUri = (text: string): string | undefined => {
    try {
        return decodeURIComponent(text)
    } catch {
        return undefined
    }
}

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
    const decodedUrl = url ? decodeUri(url.href) : ''
    if (decodedUrl === undefined) {
        problems.push(`${where}: url has invalid percent-encoding`)
    } else if (STRINGIFIED_MISSING_VALUE.test(decodedUrl) || UNDEFINED_WORD.test(decodedUrl)) {
        problems.push(`${where}: url carries a stringified undefined or null`)
    }
    if (!HTTP_METHODS.includes(request.method.toUpperCase())) {
        problems.push(`${where}: method ${request.method} is not an HTTP method`)
    }
    for (const [name, value] of Object.entries(request.headers)) {
        if (carriesMissingValue(String(value)) || /\bnull$/.test(String(value))) {
            problems.push(`${where}: header ${name} carries a stringified undefined or null`)
        }
    }
    if (UNRESOLVED_TEMPLATE.test(wireText(request))) {
        problems.push(`${where}: request carries unresolved template syntax`)
    }
    return [...problems, ...bodyProblems(request).map((problem) => `${where}: ${problem}`)]
}

const bodyProblems = (request: OutgoingRequest): string[] => {
    if (!request.body) {
        return []
    }
    const contentType = String(
        Object.entries(request.headers).find(([name]) => name.toLowerCase() === 'content-type')?.[1] ?? ''
    )
    if (contentType.includes('json')) {
        try {
            const leaves = jsonStringLeaves(parseJSON(request.body))
            return leaves.some(carriesMissingValue) ? ['JSON body carries a stringified undefined or null'] : []
        } catch {
            return ['JSON body does not parse']
        }
    }
    const values = contentType.includes('x-www-form-urlencoded')
        ? [...new URLSearchParams(request.body).values()]
        : [request.body]
    return values.some(carriesMissingValue) ? ['body carries a stringified undefined or null'] : []
}

const requestsAreWellFormed = (run: PipelineRun): string[] => [
    ...(run.requests.length === 0 ? ['no request was sent'] : []),
    ...run.requests.flatMap(requestProblems),
]

const BASE64_RUN = /[A-Za-z0-9+/]{12,}={0,2}/g

const withDecodedBase64 = (text: string): string =>
    [text, ...(text.match(BASE64_RUN) ?? []).map((run) => Buffer.from(run, 'base64').toString('utf-8'))].join('\n')

const secretsStayOutOfOutput = (run: PipelineRun): string[] => {
    if (run.sensitiveValues.length === 0) {
        return ['the run configured no sensitive value to look for']
    }
    const output = [
        ...run.printedOutput,
        ...run.invocationErrors,
        run.thrown ?? '',
        String(run.result?.error ?? ''),
    ].map(withDecodedBase64)
    return run.sensitiveValues
        .filter((secret) => output.some((text) => text.includes(secret)))
        .map((secret) => `output shows the sensitive value ${secret}`)
}

const failureIsVisible = (run: PipelineRun): string[] => {
    if (run.thrown) {
        return [run.thrown]
    }
    const failed = run.result?.error !== undefined || run.invocationErrors.length > 0
    const retrying = run.result?.finished === false && run.result.invocation.queueScheduledAt !== undefined
    return failed || retrying ? [] : ['the invocation ended as a success']
}

const hasSensitiveValues = ({ template }: TemplateCase): boolean =>
    template.inputs_schema.some((schema) => schema.secret || schema.type === 'integration')

// Every other async function reaches the network, including the helpers that call PostHog's internal API.
const ASYNC_FUNCTIONS_WITHOUT_HTTP = new Set(['sendEmail', 'sendPushNotification', 'produceToWarehouseWebhooks'])
const HTTP_ASYNC_FUNCTIONS = getRegisteredAsyncFunctionNames().filter((name) => !ASYNC_FUNCTIONS_WITHOUT_HTTP.has(name))

const sendsHttpRequests = ({ template }: TemplateCase): boolean =>
    HTTP_ASYNC_FUNCTIONS.some((name) => new RegExp(`\\b${name}\\s*\\(`).test(template.code))

const hasIntegrationInput = ({ template }: TemplateCase): boolean =>
    template.inputs_schema.some((schema) => schema.type === 'integration')

const ALL_CASES = [...DESTINATION_CASES, ...TRANSFORMATION_CASES]
const isRunnable = (templateCase: TemplateCase): boolean => !(templateCase.name in RUNS_EXEMPTIONS)
const isRunnableDestination = (templateCase: TemplateCase): boolean =>
    isRunnable(templateCase) && DESTINATION_CASES.includes(templateCase)

const checksRequests = (templateCase: TemplateCase): boolean =>
    isRunnableDestination(templateCase) && sendsHttpRequests(templateCase)
const checksSecrets = (templateCase: TemplateCase): boolean =>
    isRunnable(templateCase) && hasSensitiveValues(templateCase)
const checksIntegration = (templateCase: TemplateCase): boolean =>
    isRunnableDestination(templateCase) && hasIntegrationInput(templateCase)

// An exempt case only fails the suite once fixed if its invariant runs, so each entry must name such a case.
const EXEMPTION_SCOPES: [string, Exemptions, (templateCase: TemplateCase) => boolean][] = [
    ['runs', RUNS_EXEMPTIONS, () => true],
    ['well-formed', WELL_FORMED_EXEMPTIONS, checksRequests],
    ['failures', FAILURES_EXEMPTIONS, checksRequests],
    ['secrets', SECRETS_EXEMPTIONS, checksSecrets],
    ['integration', INTEGRATION_EXEMPTIONS, checksIntegration],
]

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
        EXEMPTION_SCOPES.flatMap(([invariant, exemptions, runsFor]) =>
            Object.keys(exemptions).map((name) => [name, invariant, runsFor] as const)
        )
    )('exemption %s names a case the %s invariant runs for', (name, _invariant, runsFor) => {
        expect(ALL_CASES.filter(runsFor).map((c) => c.name)).toContain(name)
    })

    it('runs every hog template in the registry as at least one case', () => {
        const coveredIds = new Set(ALL_CASES.map((c) => c.template.id))
        const uncoveredIds = [...HOG_FUNCTION_TEMPLATES_DESTINATIONS, ...HOG_FUNCTION_TEMPLATES_TRANSFORMATIONS]
            .filter((template) => template.code_language === 'hog' && !coveredIds.has(template.id))
            .map((template) => template.id)

        expect(uncoveredIds).toEqual([])
    })

    describe.each(DESTINATION_CASES.map((c) => [c.name, c] as const))('%s', (_name, templateCase: TemplateCase) => {
        it('runs on a representative event', async () => {
            const run = await pipeline.run(templateCase, OK)

            expectInvariant(templateCase, RUNS_EXEMPTIONS, runsWithoutError(run))
        })

        if (checksRequests(templateCase)) {
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

        if (checksSecrets(templateCase)) {
            it('keeps sensitive values out of its output, also when a request is rejected', async () => {
                const runs = [
                    await pipeline.run(templateCase, OK, { debug: true }),
                    await pipeline.run(templateCase, REJECTED, { debug: true }),
                ]

                expectInvariant(templateCase, SECRETS_EXEMPTIONS, runs.flatMap(secretsStayOutOfOutput))
            })
        }

        if (checksIntegration(templateCase)) {
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

        if (checksSecrets(templateCase)) {
            it('keeps sensitive values out of its output', async () => {
                const run = await pipeline.run(templateCase, OK, { debug: true })

                expectInvariant(templateCase, SECRETS_EXEMPTIONS, secretsStayOutOfOutput(run))
            })
        }
    })
})

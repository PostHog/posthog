import http from 'http'
import { AddressInfo } from 'net'
import { text } from 'stream/consumers'

import { EmailTrackingCodeSigner } from '~/cdp/services/messaging/helpers/tracking-code'
import { parseJSON } from '~/common/utils/json-parse'

import { CardFault, FaultList, FaultRule, SesStatusAnswer, ruleOf } from './faults'
import {
    ConfigurationSets,
    SEND_EMAIL_PATH,
    SesMessage,
    addressesOf,
    readSendEmail,
    trackingCodeOf,
    unitIdOf,
} from './ses'
import { TRUTH_PAGE_LIMIT, Truth, TruthRecord } from './truth'

export type { CardFault, FaultRule } from './faults'
export type { SesMessage } from './ses'
export { UNIT_EMAIL_DOMAIN } from './ses'
export type { TruthPage, TruthRecord } from './truth'

export type ProviderEdgeOptions = {
    port: number
    configurationSets?: ConfigurationSets
    trackingKeys?: string
}

export type ProviderEdge = {
    url: string
    records: readonly TruthRecord[]
    addFault(rule: FaultRule): string
    clearFaults(): void
    close(): Promise<void>
}

type Reply = { status: number; body?: object; errorType?: string }

function respond(res: http.ServerResponse, { status, body, errorType }: Reply): void {
    res.writeHead(status, {
        'content-type': 'application/json',
        ...(errorType ? { 'x-amzn-errortype': errorType } : {}),
    })
    res.end(body === undefined ? undefined : JSON.stringify(body))
}

function sesError(answer: SesStatusAnswer): Reply {
    return { status: answer.status, body: { message: answer.message }, errorType: answer.type }
}

function parseBody(raw: string): unknown {
    try {
        return parseJSON(raw || '{}')
    } catch {
        return undefined
    }
}

function nonNegativeInteger(value: string | null, fallback: number): number {
    const parsed = Number(value ?? fallback)
    return Number.isInteger(parsed) && parsed >= 0 ? parsed : fallback
}

export async function startProviderEdge(options: ProviderEdgeOptions): Promise<ProviderEdge> {
    const truth = new Truth()
    const faults = new FaultList()
    const signer = options.trackingKeys ? new EmailTrackingCodeSigner(options.trackingKeys, '') : undefined

    const actionIdOf = (trackingCode: string | undefined): string | undefined =>
        trackingCode === undefined ? undefined : signer?.parse(trackingCode)?.actionId

    const sendEmail = (body: unknown, req: http.IncomingMessage): Reply | 'drop-connection' => {
        const request = readSendEmail((body ?? {}) as Record<string, any>, options.configurationSets)
        if ('error' in request) {
            truth.append({ kind: 'ses.send', status: request.error.status, detail: { error: request.error.message } })
            return sesError(request.error)
        }
        const { message } = request
        const recipients = addressesOf(message.to)
        const correlation = { unitId: unitIdOf(recipients), actionId: actionIdOf(trackingCodeOf(message)) }
        const fault = faults.take(recipients)
        if (fault?.answer.kind === 'drop-connection') {
            truth.append({ kind: 'ses.send', status: 0, fault: fault.name, ...correlation, detail: {} })
            req.socket.destroy()
            return 'drop-connection'
        }
        if (fault?.answer.kind === 'status') {
            const { answer } = fault.answer
            truth.append({ kind: 'ses.send', status: answer.status, fault: fault.name, ...correlation, detail: {} })
            return sesError(answer)
        }
        const messageId = `provider-edge-${truth.records.length + 1}`
        const sent: SesMessage = { messageId, ...message }
        truth.append({ kind: 'ses.send', status: 200, ...correlation, detail: { message: sent } })
        return { status: 200, body: { MessageId: messageId } }
    }

    const addCardFault = (body: unknown): Reply => {
        const parsed = CardFault.safeParse(body)
        if (!parsed.success) {
            const problems = parsed.error.issues.map((issue) => `${issue.path.join('.') || 'fault'}: ${issue.message}`)
            return { status: 400, body: { problems } }
        }
        return { status: 201, body: { id: faults.add(ruleOf(parsed.data)) } }
    }

    const route = (req: http.IncomingMessage, url: URL, body: unknown): Reply | 'drop-connection' => {
        const faultId = /^\/_faults\/([^/]+)$/.exec(url.pathname)?.[1]
        switch (`${req.method} ${faultId === undefined ? url.pathname : '/_faults/:id'}`) {
            case `POST ${SEND_EMAIL_PATH}`:
                return sendEmail(body, req)
            case 'GET /_health':
                return { status: 200, body: { ok: true } }
            case 'GET /_truth':
                return {
                    status: 200,
                    body: truth.page(
                        nonNegativeInteger(url.searchParams.get('after'), 0),
                        nonNegativeInteger(url.searchParams.get('limit'), TRUTH_PAGE_LIMIT)
                    ),
                }
            case 'POST /_faults':
                return addCardFault(body)
            case 'DELETE /_faults':
                faults.clear()
                return { status: 204 }
            case 'DELETE /_faults/:id':
                return { status: faults.remove(faultId!) ? 204 : 404 }
            default:
                return sesError({
                    status: 404,
                    type: 'NotFoundException',
                    message: `No route for ${req.method} ${url.pathname}`,
                })
        }
    }

    const handle = async (req: http.IncomingMessage, res: http.ServerResponse): Promise<void> => {
        const body = parseBody(await text(req))
        if (body === undefined) {
            respond(res, { status: 400, body: { message: 'The body is not JSON.' } })
            return
        }
        const reply = route(req, new URL(req.url ?? '/', 'http://edge'), body)
        if (reply !== 'drop-connection') {
            respond(res, reply)
        }
    }

    const server = http.createServer((req, res) => {
        handle(req, res).catch((error: unknown) => {
            if (res.headersSent || req.socket.destroyed) {
                res.destroy()
                return
            }
            respond(
                res,
                sesError({
                    status: 400,
                    type: 'BadRequestException',
                    message: `The edge could not read the request: ${String(error)}`,
                })
            )
        })
    })
    await new Promise<void>((resolve) => server.listen(options.port, '127.0.0.1', resolve))
    const { port } = server.address() as AddressInfo

    return {
        url: `http://127.0.0.1:${port}`,
        records: truth.records,
        addFault: (rule) => faults.add(rule),
        clearFaults: () => faults.clear(),
        close: async () => {
            server.closeAllConnections()
            await new Promise<void>((resolve) => server.close(() => resolve()))
        },
    }
}

import http from 'http'
import { AddressInfo } from 'net'
import { text } from 'stream/consumers'
import { setTimeout as sleep } from 'timers/promises'

import { EmailTrackingCodeSigner } from '~/cdp/services/messaging/helpers/tracking-code'
import { parseJSON } from '~/common/utils/json-parse'

import { createCertificates } from './certificates'
import { CardFault, FaultList, FaultRule, SesStatusAnswer, ruleOf } from './faults'
import { problemsOf } from './problems'
import { Proxy, serveConnect } from './proxy'
import {
    ConfigurationSets,
    SEND_EMAIL_PATH,
    SesMessage,
    addressesOf,
    readSendEmail,
    trackingCodeOf,
    unitIdOf,
} from './ses'
import { TRUTH_PAGE_LIMIT, Truth, truthMessageOf } from './truth'

export type { CardFault, FaultRule } from './faults'
export { SesThrottleParams } from './faults'
export type { SesAttachment, SesMessage } from './ses'
export { UNIT_EMAIL_DOMAIN } from './ses'
export type { TruthAttachment, TruthHead, TruthMessage, TruthPage, TruthRecord } from './truth'

export const WEBHOOK_HOST = 'hooks.example.com'

const FAULT_OBSERVED_WITHIN_MS = 10_000
const FAULT_POLL_MS = 100

export type FaultHold = { observed(holdEnds?: AbortSignal): Promise<boolean>; release(): Promise<void> }

export type ProviderEdgeOptions = {
    port: number
    configurationSets?: ConfigurationSets
    trackingKeys?: string
    caDir?: string
    region?: string
}

export type ProviderEdge = {
    url: string
    caCertPath?: string
    sent: readonly SesMessage[]
    addFault(rule: FaultRule): string
    hold(rule: FaultRule): FaultHold
    clearFaults(): void
    close(): Promise<void>
}

type Reply = { status: number; body?: object; errorType?: string }

type Silence = 'drop-connection' | 'no-answer' | 'stalled-body'

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

function integerAtLeast(value: string | null, min: number, fallback: number): number {
    const parsed = Number(value ?? fallback)
    return Number.isInteger(parsed) && parsed >= min ? parsed : fallback
}

export async function startProviderEdge(options: ProviderEdgeOptions): Promise<ProviderEdge> {
    const truth = new Truth()
    const sent: SesMessage[] = []
    const faults = new FaultList()
    const signer = options.trackingKeys ? new EmailTrackingCodeSigner(options.trackingKeys, '') : undefined

    const actionIdOf = (trackingCode: string | undefined): string | undefined =>
        trackingCode === undefined ? undefined : signer?.parse(trackingCode)?.actionId

    const sendEmail = (body: unknown): Reply | Silence => {
        const request = readSendEmail(body, options.configurationSets)
        if ('error' in request) {
            truth.append({ kind: 'ses.send', status: request.error.status, detail: { error: request.error.message } })
            return sesError(request.error)
        }
        const { message } = request
        const recipients = addressesOf(message.to)
        const correlation = { unitId: unitIdOf(recipients), actionId: actionIdOf(trackingCodeOf(message)) }
        const fault = faults.takeSes(addressesOf([...message.to, ...(message.cc ?? []), ...(message.bcc ?? [])]))
        if (fault && fault.answer.kind !== 'status') {
            truth.append({ kind: 'ses.send', status: 0, fault: fault.name, ...correlation, detail: {} })
            return fault.answer.kind
        }
        if (fault?.answer.kind === 'status') {
            const { answer } = fault.answer
            truth.append({
                kind: 'ses.send',
                status: answer.status,
                fault: fault.name,
                ...correlation,
                detail: { errorType: answer.type },
            })
            return sesError(answer)
        }
        const messageId = `provider-edge-${truth.records.length + 1}`
        const accepted: SesMessage = { messageId, ...message }
        sent.push(accepted)
        truth.append({ kind: 'ses.send', status: 200, ...correlation, detail: { message: truthMessageOf(accepted) } })
        return { status: 200, body: { MessageId: messageId } }
    }

    const addCardFault = (body: unknown): Reply => {
        const parsed = CardFault.safeParse(body)
        if (!parsed.success) {
            return { status: 400, body: { problems: problemsOf(parsed.error, 'fault') } }
        }
        return { status: 201, body: { id: faults.add(ruleOf(parsed.data)) } }
    }

    const route = (req: http.IncomingMessage, url: URL, body: unknown): Reply | Silence => {
        const faultId = /^\/_faults\/([^/]+)$/.exec(url.pathname)?.[1]
        switch (`${req.method} ${faultId === undefined ? url.pathname : '/_faults/:id'}`) {
            case `POST ${SEND_EMAIL_PATH}`:
                return sendEmail(body)
            case 'GET /_truth/head':
                return { status: 200, body: truth.head() }
            case 'GET /_health':
                return { status: 200, body: { ok: true } }
            case 'GET /_truth':
                return {
                    status: 200,
                    body: truth.page(
                        integerAtLeast(url.searchParams.get('after'), 0, 0),
                        integerAtLeast(url.searchParams.get('limit'), 1, TRUTH_PAGE_LIMIT)
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
        const url = URL.parse(req.url ?? '/', 'http://edge')
        if (url === null) {
            respond(res, { status: 400, body: { message: 'The request target is not a URL.' } })
            return
        }
        const reply = route(req, url, body)
        if (reply === 'drop-connection') {
            req.socket.destroy()
        } else if (reply === 'stalled-body') {
            res.writeHead(200, { 'content-type': 'application/json' }).write('{"MessageId":')
        } else if (reply !== 'no-answer') {
            respond(res, reply)
        }
    }

    const receive = async (req: http.IncomingMessage, res: http.ServerResponse): Promise<void> => {
        await text(req)
        const host = (req.headers.host ?? '').replace(/:\d+$/, '')
        const target = req.url ?? '/'
        if (host !== WEBHOOK_HOST) {
            respond(res, { status: 404, body: { message: `The edge serves nothing at ${host}${target}` } })
            return
        }
        const [, unitId, actionId] = /^\/u\/([^/?]+)\/([^/?]+)/.exec(target) ?? []
        const fault = faults.takeWebhook(host)
        const status = fault?.status ?? 200
        truth.append({
            kind: 'webhook',
            status,
            fault: fault?.name,
            unitId,
            actionId,
            detail: { request: { method: req.method ?? 'GET', host, path: target } },
        })
        respond(res, { status, body: fault ? { message: `${fault.name} answered ${status}` } : { ok: true } })
    }

    const serve =
        (handler: typeof handle) =>
        (req: http.IncomingMessage, res: http.ServerResponse): void => {
            handler(req, res).catch((error: unknown) => {
                if (res.headersSent || req.socket.destroyed) {
                    res.destroy()
                    return
                }
                respond(
                    res,
                    sesError({ status: 500, type: 'InternalFailure', message: `The edge failed: ${String(error)}` })
                )
            })
        }

    const server = http.createServer(serve(handle))
    const certificates = options.caDir
        ? await createCertificates(options.caDir, [WEBHOOK_HOST, `sns.${options.region ?? 'us-east-1'}.amazonaws.com`])
        : undefined
    const proxy: Proxy | undefined =
        certificates && serveConnect(server, certificates.leaves, http.createServer(serve(receive)))
    await new Promise<void>((resolve, reject) => {
        server.once('error', reject)
        server.listen(options.port, '127.0.0.1', () => {
            server.off('error', reject)
            resolve()
        })
    })
    const { port } = server.address() as AddressInfo

    return {
        url: `http://127.0.0.1:${port}`,
        caCertPath: certificates?.caCertPath,
        sent,
        addFault: (rule) => faults.add(rule),
        hold: (rule) => {
            const id = faults.add(rule)
            return {
                observed: async (holdEnds) => {
                    const deadline = Date.now() + FAULT_OBSERVED_WITHIN_MS
                    const answeredInWindow = (): boolean => (faults.firstAppliedAt(id) ?? Infinity) <= deadline
                    while (Date.now() <= deadline && !holdEnds?.aborted && !answeredInWindow()) {
                        await sleep(FAULT_POLL_MS, undefined, { signal: holdEnds }).catch(() => undefined)
                    }
                    return answeredInWindow()
                },
                release: () => {
                    faults.remove(id)
                    return Promise.resolve()
                },
            }
        },
        clearFaults: () => faults.clear(),
        close: async () => {
            proxy?.close()
            server.closeAllConnections()
            await new Promise<void>((resolve) => server.close(() => resolve()))
        },
    }
}

import http from 'http'
import { AddressInfo } from 'net'

import {
    TEMPLATE_SEND_TOKEN_CLAIMS,
    TransactionalEmailRequestSchema,
} from '~/cdp/services/hogflows/transactional-email'
import { PosthogJwtAudience } from '~/cdp/utils/jwt-utils'
import { ScopedServiceJwt } from '~/cdp/utils/scoped-service-jwt'
import { parseJSON } from '~/common/utils/json-parse'

import { UNIT_EMAIL_DOMAIN } from '../provider-edge'
import { OfferContext, bounceFollowup, transactionalEmail } from './traffic'

const SECRET = 'scenario-transactional-secret'
const UNIT = { unitId: 'run-a-1', teamId: 7, flowId: 'flow-7' }
const ROUTE = `/api/projects/${UNIT.teamId}/hog_flows/${UNIT.flowId}/transactional_email`

type Answer = { status: number; body: object }

function startCdpApi(answer: Answer): Promise<{ url: string; received: object[]; close(): Promise<void> }> {
    const verifier = new ScopedServiceJwt(PosthogJwtAudience.WORKFLOWS_SEND_TRANSACTIONAL_EMAIL, SECRET)
    const received: object[] = []
    const server = http.createServer((req, res) => {
        let raw = ''
        req.on('data', (chunk) => (raw += chunk))
        req.on('end', () => {
            const claims = verifier.verify(String(req.headers.authorization).replace(/^Bearer /, ''))
            const authorized =
                claims.team_id === UNIT.teamId &&
                claims.hog_flow_id === UNIT.flowId &&
                claims.kind === TEMPLATE_SEND_TOKEN_CLAIMS.kind
            const body = TransactionalEmailRequestSchema.strict().parse(parseJSON(raw))
            received.push({ method: req.method, url: req.url, authorized, body })
            res.writeHead(answer.status, { 'content-type': 'application/json' }).end(JSON.stringify(answer.body))
        })
    })
    return new Promise((resolve) =>
        server.listen(0, '127.0.0.1', () =>
            resolve({
                url: `http://127.0.0.1:${(server.address() as AddressInfo).port}`,
                received,
                close: () => new Promise((closed) => server.close(() => closed())),
            })
        )
    )
}

const contextFor = (url: string, settled: string | undefined = undefined): OfferContext => ({
    producer: { produce: () => Promise.reject(new Error('the transactional kind never produces')) },
    eventsTopic: 'unused',
    cdpApi: { url, jwt: new ScopedServiceJwt(PosthogJwtAudience.WORKFLOWS_SEND_TRANSACTIONAL_EMAIL, SECRET) },
    sesFeedback: { settled: (unitId) => Promise.resolve(unitId === UNIT.unitId ? settled : 'another unit') },
})

describe('transactional_email traffic', () => {
    it.each<[string, Answer, object]>([
        ['accepts a queued send', { status: 202, body: { status: 'queued' } }, { accepted: true }],
        [
            'journals a refusal with its status and outcome',
            { status: 422, body: { error: 'recipient_suppressed' } },
            { accepted: false, status: 422, outcome: 'recipient_suppressed' },
        ],
    ])('%s from the template route, called with a token for the team and flow', async (_story, answer, expected) => {
        const cdpApi = await startCdpApi(answer)
        try {
            expect(await transactionalEmail.offer(UNIT, contextFor(cdpApi.url))).toEqual(expected)
            expect(cdpApi.received).toEqual([
                {
                    method: 'POST',
                    url: ROUTE,
                    authorized: true,
                    body: { to: `${UNIT.unitId}@${UNIT_EMAIL_DOMAIN}`, distinct_id: UNIT.unitId, variables: {} },
                },
            ])
        } finally {
            await cdpApi.close()
        }
    })

    it('journals a transport error when cdp-api cannot be reached', async () => {
        const cdpApi = await startCdpApi({ status: 202, body: {} })
        await cdpApi.close()

        expect(await transactionalEmail.offer(UNIT, contextFor(cdpApi.url))).toEqual({
            accepted: false,
            transportError: expect.stringContaining('ECONNREFUSED'),
        })
    })
})

describe('bounce_followup traffic', () => {
    it.each<[string, string | undefined, object, number]>([
        [
            'sends the follow-up through the template route once its feedback settled',
            undefined,
            { accepted: false, status: 422, outcome: 'recipient_suppressed' },
            1,
        ],
        [
            'leaves the follow-up unsent when its feedback did not settle',
            'the edge recorded no SES feedback within 60s',
            { notSent: 'the edge recorded no SES feedback within 60s' },
            0,
        ],
    ])('%s', async (_story, settled, expected, sends) => {
        const cdpApi = await startCdpApi({ status: 422, body: { error: 'recipient_suppressed' } })
        try {
            expect(await bounceFollowup.followUp!.offer(UNIT, contextFor(cdpApi.url, settled))).toEqual(expected)
            expect(cdpApi.received).toHaveLength(sends)
        } finally {
            await cdpApi.close()
        }
    })
})

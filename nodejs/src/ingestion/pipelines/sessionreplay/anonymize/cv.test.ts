import { gunzipSync, gzipSync } from 'zlib'

import { parseJSON } from '~/common/utils/json-parse'

import { anonymizeEvent } from './anonymize-event'
import { defaultAllowLists } from './default-dict'

const compress = (v: unknown): string => gzipSync(Buffer.from(JSON.stringify(v))).toString('latin1')
const decompress = (s: string): any => parseJSON(gunzipSync(Buffer.from(s, 'latin1')).toString('utf8'))

describe('anonymize/cv', () => {
    const ctx = { allow: defaultAllowLists() }

    it('round-trips a cv-compressed FullSnapshot and scrubs the DOM text', () => {
        const payload = {
            node: {
                type: 0,
                id: 1,
                childNodes: [
                    {
                        type: 2,
                        id: 2,
                        tagName: 'div',
                        attributes: {},
                        childNodes: [{ type: 3, id: 3, textContent: 'Hello SecretName' }],
                    },
                ],
            },
            initialOffset: { top: 0, left: 0 },
        }
        const event: any = { type: 2, timestamp: 1, cv: 'v2', data: compress(payload) }

        expect(anonymizeEvent(ctx, event)).toBe(true)
        const out = decompress(event.data)
        expect(out.node.childNodes[0].childNodes[0].textContent).toBe('Hello **********')
    })

    it('round-trips a cv-compressed Mutation and scrubs the text sub-field', () => {
        const event: any = {
            type: 3,
            timestamp: 1,
            cv: 'v2',
            data: {
                source: 0,
                texts: compress([{ id: 7, value: 'Hello SecretName' }]),
                attributes: compress([]),
                removes: compress([]),
                adds: compress([]),
            },
        }

        expect(anonymizeEvent(ctx, event)).toBe(true)
        const outTexts = decompress(event.data.texts)
        expect(outTexts[0].value).toBe('Hello **********')
    })

    it('round-trips a cv-compressed Mutation and media-scrubs an rr_src attribute sub-field', () => {
        const leakUrl =
            'https://widget.example-vendor.co/v2/app/?widgetToken=eyJ0eXAiOiJKV1QifQ.eyJzdWIiOiJ1c2VyX2Zha2UxMjMifQ.fakesignature&refreshToken=FakeRefreshTok3nValue000&user=%7B%22email%22%3A%22john.fakename%40example.com%22%7D'
        const event: any = {
            type: 3,
            timestamp: 1,
            cv: 'v2',
            data: { source: 0, attributes: compress([{ id: 7, attributes: { rr_src: leakUrl } }]) },
        }
        expect(anonymizeEvent(ctx, event)).toBe(true)
        const outAttrs = decompress(event.data.attributes)[0].attributes
        expect(outAttrs.rr_src).toMatch(/^data:image\/svg\+xml/)
        for (const secret of ['fakesignature', 'FakeRefreshTok3nValue000', 'john.fakename']) {
            expect(JSON.stringify(outAttrs)).not.toContain(secret)
        }
    })

    it('scrubs a cv Mutation whose sub-fields are already decompressed arrays', () => {
        // Some producers/exporters emit cv events with plain-array sub-fields.
        // These must still be scrubbed (in place), not skipped as "absent".
        const event: any = {
            type: 3,
            timestamp: 1,
            cv: '2024-10',
            data: {
                source: 0,
                texts: [{ id: 7, value: 'Hello SecretName' }],
                attributes: [],
                removes: [],
                adds: [],
            },
        }
        expect(anonymizeEvent(ctx, event)).toBe(true)
        // Stays an array (not re-compressed to a string) and is scrubbed in place.
        expect(Array.isArray(event.data.texts)).toBe(true)
        expect(event.data.texts[0].value).toBe('Hello **********')
    })

    it('scrubs a cv FullSnapshot whose data is already a decompressed object', () => {
        const event: any = {
            type: 2,
            timestamp: 1,
            cv: '2024-10',
            data: {
                node: {
                    type: 0,
                    id: 1,
                    childNodes: [{ type: 3, id: 2, textContent: 'Hello SecretName' }],
                },
                initialOffset: { top: 0, left: 0 },
            },
        }
        expect(anonymizeEvent(ctx, event)).toBe(true)
        expect(event.data.node.childNodes[0].textContent).toBe('Hello **********')
    })

    it('throws on a cv FullSnapshot whose data string is not valid latin-1', () => {
        // A codepoint > 0xFF cannot be a latin-1 gzip byte; decoding must throw
        // so the caller fails closed rather than writing the raw blob.
        const event: any = { type: 2, timestamp: 1, cv: '2024-10', data: 'not-Ā-gzip' }
        expect(() => anonymizeEvent(ctx, event)).toThrow()
    })

    it('does not gunzip an absent/empty sub-field', () => {
        // texts present, attributes/removes/adds absent — must still scrub texts.
        const event: any = {
            type: 3,
            timestamp: 1,
            cv: 'v2',
            data: { source: 0, texts: compress([{ id: 1, value: 'Hello SecretName' }]) },
        }
        expect(anonymizeEvent(ctx, event)).toBe(true)
        expect(decompress(event.data.texts)[0].value).toBe('Hello **********')
    })

    it('fails closed when a compressed sub-field does not decode to an array', () => {
        // A decodable-but-non-array sub-field is malformed; must throw (→ message dropped) rather than zero it.
        const event: any = {
            type: 3,
            timestamp: 1,
            cv: 'v2',
            data: { source: 0, texts: compress({ not: 'an array' }) },
        }
        expect(() => anonymizeEvent(ctx, event)).toThrow()
    })
})

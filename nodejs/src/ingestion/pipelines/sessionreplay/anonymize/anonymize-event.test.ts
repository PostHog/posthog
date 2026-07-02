import { ParsedMessageData } from '~/ingestion/pipelines/sessionreplay/kafka/types'
import { ImageScrubEmitDeps, TopicMessage } from '~/ingestion/pipelines/sessionreplay/ml-mirror/image-scrub/producer'

import { anonymizeEvent, anonymizeParsedMessage } from './anonymize-event'
import { defaultAllowLists } from './default-dict'

describe('anonymize/event router', () => {
    const ctx = { allow: defaultAllowLists() }

    it('scrubs Input text', () => {
        const event: any = {
            type: 3,
            timestamp: 1,
            data: { source: 5, id: 1, text: 'Hello SecretName', isChecked: false },
        }
        expect(anonymizeEvent(ctx, event)).toBe(true)
        expect(event.data.text).toBe('Hello **********')
    })

    it('URL-scrubs Meta href and leaves width/height untouched', () => {
        const event: any = {
            type: 4,
            timestamp: 1,
            data: { href: 'https://example.com/api/v1/users/abc', width: 1280, height: 720 },
        }
        expect(anonymizeEvent(ctx, event)).toBe(true)
        expect(event.data.href).toBe('https://example.com/api/v1/users/[redacted]')
        expect(event.data.width).toBe(1280)
        expect(event.data.height).toBe(720)
    })

    it('passes through a FullSnapshot with nothing to scrub', () => {
        const event: any = {
            type: 2,
            timestamp: 1,
            data: { node: { type: 0, id: 1, childNodes: [] }, initialOffset: { top: 0, left: 0 } },
        }
        expect(anonymizeEvent(ctx, event)).toBe(false)
    })

    it('passes through mouse-move incremental events', () => {
        const event: any = {
            type: 3,
            timestamp: 1,
            data: { source: 1, positions: [{ x: 1, y: 2, id: 3, timeOffset: 0 }] },
        }
        expect(anonymizeEvent(ctx, event)).toBe(false)
    })

    it('passes through Load events', () => {
        const event: any = { type: 1, timestamp: 1, data: {} }
        expect(anonymizeEvent(ctx, event)).toBe(false)
    })

    it('scrubs console plugin payload strings', () => {
        const event: any = {
            type: 6,
            timestamp: 1,
            data: { plugin: 'rrweb/console@1', payload: { level: 'info', payload: ['Hello SecretName'], trace: [] } },
        }
        expect(anonymizeEvent(ctx, event)).toBe(true)
        expect(event.data.payload.payload[0]).toBe('Hello **********')
    })

    it('scrubs network plugin request name and body', () => {
        const event: any = {
            type: 6,
            timestamp: 1,
            data: {
                plugin: 'rrweb/network@1',
                payload: { requests: [{ name: 'https://example.com/user/abc/edit', requestBody: 'Hello SecretName' }] },
            },
        }
        expect(anonymizeEvent(ctx, event)).toBe(true)
        expect(event.data.payload.requests[0].name).toBe('https://example.com/user/[redacted]/edit')
        expect(event.data.payload.requests[0].requestBody).toBe('Hello **********')
    })

    it('scrubs an arbitrary Custom payload generically', () => {
        const event: any = { type: 5, timestamp: 1, data: { tag: 'x', payload: { note: 'Hello SecretName' } } }
        expect(anonymizeEvent(ctx, event)).toBe(true)
        expect(event.data.payload.note).toBe('Hello **********')
    })

    it('scrubs an unknown plugin payload generically', () => {
        const event: any = {
            type: 6,
            timestamp: 1,
            data: { plugin: 'some/other-plugin@1', payload: { note: 'Hello SecretName' } },
        }
        expect(anonymizeEvent(ctx, event)).toBe(true)
        expect(event.data.payload.note).toBe('Hello **********')
    })

    it.each([
        ['IncrementalSnapshot', 3],
        ['Meta', 4],
        ['Custom', 5],
        ['Plugin', 6],
    ])('passes through %s events whose data is not an object', (_name, type) => {
        const event: any = { type, timestamp: 1, data: null }
        expect(anonymizeEvent(ctx, event)).toBe(false)
    })

    it('passes through incremental events with an unhandled source', () => {
        const event: any = { type: 3, timestamp: 1, data: { source: 99, foo: 'bar' } }
        expect(anonymizeEvent(ctx, event)).toBe(false)
    })

    it('passes through (no change) a malformed event with non-object data', () => {
        const event: any = { type: 2, timestamp: 1, data: null }
        expect(anonymizeEvent(ctx, event)).toBe(false)
    })

    it('throws when a scrubber errors, so the caller can fail closed', () => {
        // A throwing getter on `data` forces an exception inside routing. The
        // error must propagate (not be swallowed as "nothing to scrub").
        const event: any = {
            type: 2,
            timestamp: 1,
            get data() {
                throw new Error('boom')
            },
        }
        expect(() => anonymizeEvent(ctx, event)).toThrow('boom')
    })

    describe('image-scrub drain', () => {
        // A real 1x1 PNG, so it passes the magic-byte check and routes as an advanced image.
        const DATA_URI =
            'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACgAAAAoCAIAAAADnC86AAAACXBIWXMAAAPoAAAD6AG1e1JrAAAAR0lEQVR4nO3YsQkAIAxEUeu//1A3ljvY2DywD0iSR+6svryjcL56mivjlAUyKzNIhMWwGBaHxbAYFodF12IO80QRE770HDddvGtfTNaUfqIAAAAASUVORK5CYII='

        // A FullSnapshot carrying one <img> with an inline rr_dataURL (advanced-route).
        function messageWithInlineImage(): { message: ParsedMessageData; img: Record<string, any> } {
            const img = {
                type: 2,
                id: 2,
                tagName: 'img',
                attributes: { rr_dataURL: DATA_URI, width: 300, height: 300 },
                childNodes: [],
            }
            const message = {
                eventsByWindowId: {
                    w1: [
                        {
                            type: 2,
                            timestamp: 1,
                            data: { node: { type: 0, id: 1, childNodes: [img] }, initialOffset: { top: 0, left: 0 } },
                        },
                    ],
                },
            } as unknown as ParsedMessageData
            return { message, img }
        }

        it('emits an advanced <img> to the topic and writes the reference in place', async () => {
            const produced: TopicMessage[] = []
            const imageScrub: ImageScrubEmitDeps = {
                setBatchContentKeysRedis: (keys) => Promise.resolve(keys.map(() => true)),
                deleteBatchContentKeysRedis: () => Promise.resolve(),
                produceBatchImagesKafka: (messages) => {
                    produced.push(...messages)
                    return Promise.resolve()
                },
            }
            const { message, img } = messageWithInlineImage()

            const { failed } = await anonymizeParsedMessage({ allow: defaultAllowLists(), imageScrub }, message, 42)

            expect(failed).toBe(false)
            expect(produced).toHaveLength(1)
            expect(img.attributes.rr_dataURL).toMatch(/^image:42:[A-Za-z0-9_-]{22}$/) // reference written in place
            expect(produced[0].key).toBe(img.attributes.rr_dataURL) // topic key == the substituted reference
        })

        it('fails closed (drops the message) when the emit throws', async () => {
            const imageScrub: ImageScrubEmitDeps = {
                setBatchContentKeysRedis: (keys) => Promise.resolve(keys.map(() => true)),
                deleteBatchContentKeysRedis: () => Promise.resolve(),
                produceBatchImagesKafka: () => Promise.reject(new Error('broker down')),
            }
            const { message } = messageWithInlineImage()

            const { failed } = await anonymizeParsedMessage({ allow: defaultAllowLists(), imageScrub }, message, 42)

            expect(failed).toBe(true)
        })

        it('falls back to blur (no emit) when no team id is present', async () => {
            const produced: TopicMessage[] = []
            const imageScrub: ImageScrubEmitDeps = {
                setBatchContentKeysRedis: (keys) => Promise.resolve(keys.map(() => true)),
                deleteBatchContentKeysRedis: () => Promise.resolve(),
                produceBatchImagesKafka: (messages) => {
                    produced.push(...messages)
                    return Promise.resolve()
                },
            }
            const { message, img } = messageWithInlineImage()

            // teamId omitted -> advanced route can't build a reference, so nothing is emitted.
            const { failed } = await anonymizeParsedMessage({ allow: defaultAllowLists(), imageScrub }, message)

            expect(failed).toBe(false)
            expect(produced).toHaveLength(0)
            expect(img.attributes.rr_dataURL).not.toMatch(/^image:/) // blanked/blurred, not referenced
        })
    })
})

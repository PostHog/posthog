import { PipelineResultType } from '~/ingestion/framework/results'

import { createAnonymizeStep } from './anonymize-step'
import { defaultAllowLists } from './anonymize/default-dict'
import { ParsedMessageData } from './kafka/types'

describe('anonymize-step', () => {
    const step = createAnonymizeStep({ scrubContext: { allow: defaultAllowLists() } })
    const team = { teamId: 1, consoleLogIngestionEnabled: true, aiTrainingOptedIn: true, firstPartyHosts: [] }

    const parsedMessageWith = (eventsByWindowId: Record<string, any[]>): ParsedMessageData =>
        ({ eventsByWindowId }) as unknown as ParsedMessageData

    it('scrubs events across all windows in place and returns OK', async () => {
        const parsedMessage = parsedMessageWith({
            win1: [{ type: 3, timestamp: 1, data: { source: 5, id: 1, text: 'Hello SecretName', isChecked: false } }],
            win2: [{ type: 4, timestamp: 2, data: { href: 'https://example.com/user/abc/edit', width: 1, height: 1 } }],
        })

        const result = await step({ parsedMessage, team })

        expect(result.type).toBe(PipelineResultType.OK)
        expect((parsedMessage.eventsByWindowId.win1[0] as any).data.text).toBe('Hello **********')
        expect((parsedMessage.eventsByWindowId.win2[0] as any).data.href).toBe(
            'https://example.com/user/[redacted]/edit'
        )
    })

    it('blurs a data-image media source via the deferred job pass', async () => {
        // Small patterned PNG (portable across libvips/libpng builds; a solid color would blur to
        // identical bytes, so we use a checkerboard the blur visibly changes).
        const onePxPng =
            'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAACXBIWXMAAAPoAAAD6AG1e1JrAAAAJUlEQVQokWN4plEBRyInbOAIlzjDINRAjCJk8cGoYRAG60iMBwA8H08Qor0ygQAAAABJRU5ErkJggg=='
        const parsedMessage = parsedMessageWith({
            win1: [
                {
                    type: 2,
                    timestamp: 1,
                    data: {
                        node: {
                            type: 0,
                            id: 1,
                            childNodes: [
                                { type: 2, id: 2, tagName: 'img', attributes: { src: onePxPng }, childNodes: [] },
                            ],
                        },
                        initialOffset: { top: 0, left: 0 },
                    },
                },
            ],
        })

        await step({ parsedMessage, team })

        const src = (parsedMessage.eventsByWindowId.win1[0] as any).data.node.childNodes[0].attributes.src
        // Blurred into a fresh PNG, not left as the placeholder or the original.
        expect(src.startsWith('data:image/png;base64,')).toBe(true)
        expect(src).not.toBe(onePxPng)
    })

    it('passes through events with no scrubbable content', async () => {
        const parsedMessage = parsedMessageWith({
            win1: [{ type: 3, timestamp: 1, data: { source: 1, positions: [] } }],
        })

        const result = await step({ parsedMessage, team })

        expect(result.type).toBe(PipelineResultType.OK)
        expect((parsedMessage.eventsByWindowId.win1[0] as any).data.source).toBe(1)
    })

    it('fails closed: drops the message when an event cannot be anonymized', async () => {
        // A FullSnapshot whose data string is not valid latin-1 throws during scrubbing.
        const parsedMessage = parsedMessageWith({
            win1: [{ type: 2, timestamp: 1, cv: '2024-10', data: 'not-Ā-gzip' }],
        })

        const result = await step({ parsedMessage, team })

        expect(result.type).toBe(PipelineResultType.DROP)
        expect(result.type === PipelineResultType.DROP && result.reason).toBe('anonymize_failed')
    })
})

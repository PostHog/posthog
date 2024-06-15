import { PreIngestionEvent } from '../../../../src/types'
import {
    embedErrorEvent,
    initEmbeddingModel,
    resetEmbeddingModel,
} from '../../../../src/worker/ingestion/event-pipeline/embedErrorEventStep'
import { EventPipelineRunner } from '../../../../src/worker/ingestion/event-pipeline/runner'

// Or things explode?! when trying to run the onnx runtime code
const originalImplementation = Array.isArray
// @ts-expect-error - TS doesn't like us assigning to a read-only property
Array.isArray = jest.fn((type) => {
    const constructorName = type?.constructor?.name
    if (constructorName === 'Float32Array' || constructorName === 'BigInt64Array') {
        return true
    }

    return originalImplementation(type)
})

/**
 * The node that is running jest needs to be run with the `--experimental-vm-modules` flag
 * for these tests to run successfully. 😭
 */
describe('embedErrorStep', () => {
    beforeEach(() => {
        resetEmbeddingModel()
    })

    it('does nothing if not initialised', async () => {
        const event = { event: '$exception' }
        const processed = await embedErrorEvent(
            {} as unknown as EventPipelineRunner,
            event as unknown as PreIngestionEvent
        )
        expect(processed).toBe(event)
        expect(event).not.toHaveProperty('$embedding')
    })

    it('can be initialised', async () => {
        const pipeline = await initEmbeddingModel(true)
        expect(pipeline).not.toBeNull()
    })

    it('can skip initialisation', async () => {
        const pipeline = await initEmbeddingModel(false)
        expect(pipeline).toBeNull()
    })

    it('can embed a range of inputs without varying exception type', async () => {
        await initEmbeddingModel(true)

        const exampleEmbeddings = [
            // group 1
            "TypeError: Cannot read property 'length' of undefined",
            "TypeError: Cannot read property 'len' of undefined",
            "TypeError: Cannot read property 'l' of undefined",
            // is this different enough to form group 2?
            "TypeError: Cannot read property 'do not have a cow' of undefined",
            // group 3 - these are progressively different, even though a human can see a vague connection
            'In the quiet moments between the stars, where the light of distant suns barely touched the darkness, he found a sense of peace, a momentary respite from the endless, chaotic dance of existence.',
            'In the quiet moments between the cars, where the light of the nearby store barely touched the darkness, he found a sense of peace, a momentary respite from the endless, chaotic dance of existence.',
            'In the quite distant cars, where the light barely touched the darkness',
            'In the far light and darkness',
            // group 4 - these are all the same
            'Oh, the places you’ll go and the things you will see, in a world full of wonders as vast as the sea!',
            'Oh, the places you’ll go and the things you will see, in a world full of wonders as vast as the sea!',
            'Oh, the places you’ll go and the things you will see, in a world full of wonders as vast as the sea!',
            'Oh, the places you’ll go and the things you will see, in a world full of wonders as vast as the sea!',
            // group 5 - green eggs and ham
            'I am Sam.',
            'Sam I am.',
            'That Sam-Iam!',
            'That Sam-Iam!',
            'I do not like that Sam-I-am!',
        ]
            .map((message) => ({
                event: '$exception',
                properties: { $exception_message: message, $exception_type: 'example' },
            }))
            .map(async (event) => ({
                pre: {
                    m: event.properties.$exception_message,
                },
                post: await embedErrorEvent(
                    {} as unknown as EventPipelineRunner,
                    event as unknown as PreIngestionEvent
                ),
            }))

        expect(await Promise.all(exampleEmbeddings)).toMatchSnapshot()
    })
})

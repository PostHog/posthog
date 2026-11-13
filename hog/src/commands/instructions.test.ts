import { describe, expect, test } from 'bun:test'

import { TOPICS } from '@/instructions/topics'
import { runHog } from '@/testing'

const TOPIC_NAMES = TOPICS.map((topic) => topic.name)

describe('hog instructions', () => {
    test('the overview names a command for every topic', async () => {
        const result = await runHog(['instructions'])

        expect(result.exitCode).toBe(0)
        const page = result.json() as { topic: string | null; text: string }
        expect(page.topic).toBeNull()
        for (const name of TOPIC_NAMES) {
            expect(page.text).toContain(`hog instructions ${name}`)
        }
    })

    test.each(TOPICS.map((topic) => [topic.name, topic.text]))('prints the %s topic', async (name, text) => {
        const result = await runHog(['instructions', name])

        expect(result.exitCode).toBe(0)
        expect(result.json()).toMatchObject({ kind: 'page', topic: name, text })
    })

    test('--list lists every topic', async () => {
        const result = await runHog(['instructions', '--list'])

        expect(result.exitCode).toBe(0)
        const { topics } = result.json() as { topics: { name: string }[] }
        expect(topics.map((topic) => topic.name)).toEqual(TOPIC_NAMES)
    })

    test('an unknown topic is a usage error that lists the topics', async () => {
        const result = await runHog(['instructions', 'flags'])

        expect(result.exitCode).toBe(2)
        const error = result.error()
        expect(error.code).toBe('unknown_topic')
        for (const name of TOPIC_NAMES) {
            expect(error.hint).toContain(name)
        }
    })

    test.each([
        ['query', 'hog query --help'],
        ['schema', 'hog schema --help'],
        ['login', 'hog auth login --help'],
    ])('the command name %s as the topic points to its --help', async (topic, help) => {
        const result = await runHog(['instructions', topic])

        expect(result.exitCode).toBe(2)
        expect(result.error()).toMatchObject({ code: 'unknown_topic', hint: expect.stringContaining(`\`${help}\``) })
    })
})

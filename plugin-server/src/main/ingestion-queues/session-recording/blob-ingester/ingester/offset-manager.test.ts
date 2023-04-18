import { beforeEach, expect, it, describe, vi } from 'vitest'

import { OffsetManager } from './offset-manager'

vi.mock('../utils/kafka')

describe('offset-manager', () => {
    const TOPIC = 'test-session-recordings'

    let offsetManager: OffsetManager
    beforeEach(async () => {
        offsetManager = new OffsetManager()
    })

    it('collects new offsets', async () => {
        offsetManager.addOffset(TOPIC, 1, 1)
        offsetManager.addOffset(TOPIC, 2, 1)
        offsetManager.addOffset(TOPIC, 3, 4)
        offsetManager.addOffset(TOPIC, 1, 2)
        offsetManager.addOffset(TOPIC, 1, 5)
        offsetManager.addOffset(TOPIC, 3, 4)

        expect(offsetManager.offsetsByPartionTopic).toEqual(
            new Map([
                ['test-session-recordings-1', [1, 2, 5]],
                ['test-session-recordings-2', [1]],
                ['test-session-recordings-3', [4, 4]],
            ])
        )
    })

    it('removes offsets', async () => {
        offsetManager.addOffset(TOPIC, 1, 1)
        offsetManager.addOffset(TOPIC, 2, 1)
        offsetManager.addOffset(TOPIC, 3, 4)
        offsetManager.addOffset(TOPIC, 1, 2)
        offsetManager.addOffset(TOPIC, 1, 5)
        offsetManager.addOffset(TOPIC, 3, 4)

        offsetManager.removeOffsets(TOPIC, 1, [1, 2])

        expect(offsetManager.offsetsByPartionTopic).toEqual(
            new Map([
                ['test-session-recordings-1', [5]],
                ['test-session-recordings-2', [1]],
                ['test-session-recordings-3', [4, 4]],
            ])
        )
    })

    it.each([
        [[1], 1],
        [[2, 5, 10], null],
        [[1, 2, 3, 9], 3],
    ])('commits the appropriate offset ', async (removals: number[], expectation: number | null) => {
        ;[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].forEach((offset) => {
            offsetManager.addOffset(TOPIC, 1, offset)
        })

        const result = await offsetManager.removeOffsets(TOPIC, 1, removals)

        expect(result).toEqual(expectation)
    })
})

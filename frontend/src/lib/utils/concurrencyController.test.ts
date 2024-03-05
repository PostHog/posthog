import { delay } from 'lib/utils'

import { ConcurrencyController } from './concurrencyController'

describe('concurrencyController', () => {
    const setup = (): {
        concurrencyController: ConcurrencyController
        results: string[]
        run: (n: number, priority: number, abortController?: AbortController) => Promise<number>
    } => {
        const concurrencyController = new ConcurrencyController(1)
        const results: string[] = []
        const run = async (n: number, priority: number, abortController?: AbortController): Promise<number> => {
            return concurrencyController.run({
                fn: async () => {
                    results.push('enter ' + n)
                    await delay(10)
                    results.push('exit ' + n)
                    return n
                },
                priority,
                abortController: abortController || new AbortController(),
            })
        }

        return { concurrencyController, results, run }
    }

    it('should execute one function at a time, sorted by priority', async () => {
        const { run, results } = setup()
        await Promise.allSettled([run(1, 1), run(3, 3), run(2, 2), run(4, 4)])

        expect(results).toEqual(['enter 1', 'exit 1', 'enter 2', 'exit 2', 'enter 3', 'exit 3', 'enter 4', 'exit 4'])
    })

    it('should eagerly execute the first item regardless of priority', async () => {
        const { run, results } = setup()

        await Promise.allSettled([run(4, 4), run(1, 1), run(3, 3), run(2, 2)])

        expect(results).toEqual(['enter 4', 'exit 4', 'enter 1', 'exit 1', 'enter 2', 'exit 2', 'enter 3', 'exit 3'])
    })

    it('should not start a new item if the item has been aborted', async () => {
        const { run, results } = setup()
        const abortController = new AbortController()
        abortController.abort()
        await Promise.allSettled([run(1, 1, abortController), run(2, 2)])
        expect(results).toEqual(['enter 2', 'exit 2'])
    })

    it('should not deadlock if an item is aborted while running', async () => {
        const concurrencyController = new ConcurrencyController(1)
        const results: string[] = []
        const run = async (n: number, priority: number): Promise<void> => {
            const abortController = new AbortController()
            await concurrencyController.run({
                fn: async () => {
                    results.push('enter ' + n)
                    await delay(10)
                    if (n === 1 || n === 3) {
                        abortController.abort()
                        await delay(10)
                        throw new Error()
                    } else {
                        results.push('exit ' + n)
                    }
                },
                priority,
                abortController,
            })
        }
        await Promise.allSettled([run(1, 1), run(3, 3), run(2, 2), run(4, 4)])

        expect(results).toEqual(['enter 1', 'enter 2', 'exit 2', 'enter 3', 'enter 4', 'exit 4'])
    })

    it('should return the correct value', async () => {
        const { run, results } = setup()
        const returnValues = await Promise.all([run(1, 1), run(3, 3), run(2, 2), run(4, 4)])

        expect(results).toEqual(['enter 1', 'exit 1', 'enter 2', 'exit 2', 'enter 3', 'exit 3', 'enter 4', 'exit 4'])
        expect(returnValues).toEqual([1, 3, 2, 4])
    })

    it('should reject rather than throw if a run function throws', async () => {
        const concurrencyController = new ConcurrencyController(1)
        const promise = concurrencyController.run({
            fn: async () => {
                throw new Error('test')
            },
            abortController: new AbortController(),
        })

        await expect(promise).rejects.toThrow('test')
    })

    it('should reject when aborting an in-progress task', async () => {
        const concurrencyController = new ConcurrencyController(1)
        const abortController = new AbortController()
        const promise = concurrencyController.run({
            fn: async () => {
                await delay(200)
            },
            abortController,
        })
        abortController.abort()

        await expect(promise).rejects.toEqual(expect.objectContaining({ name: 'AbortError' }))
    })

    it('should not deadlock when given already-resolved promises', async () => {
        const concurrencyController = new ConcurrencyController(1)
        const resolved = Promise.resolve(42)

        const run = (): Promise<number> => {
            return concurrencyController.run({
                fn: async () => resolved,
                abortController: new AbortController(),
            })
        }
        expect(await Promise.all([run(), run()])).toEqual([42, 42])
    })

    it('should have an error with name AbortError when aborted', async () => {
        const { run } = setup()
        const abortController = new AbortController()
        abortController.abort()
        const promise = run(1, 1, abortController)
        await expect(promise).rejects.toEqual(expect.objectContaining({ name: 'AbortError' }))
    })

    it('can use a parallelismLimit of 2', async () => {
        const { run, results, concurrencyController } = setup()
        concurrencyController.setConcurrencyLimit(2)
        await Promise.allSettled([run(1, 1), run(1, 1), run(3, 3), run(3, 3), run(2, 2), run(2, 2)])
        expect(results).toEqual([
            'enter 1',
            'enter 1',
            'exit 1',
            'enter 2',
            'exit 1',
            'enter 2',
            'exit 2',
            'enter 3',
            'exit 2',
            'enter 3',
            'exit 3',
            'exit 3',
        ])
    })
})

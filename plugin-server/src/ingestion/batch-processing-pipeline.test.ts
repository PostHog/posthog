import { dlq, drop, redirect, success } from '../worker/ingestion/event-pipeline/pipeline-step-result'
import { BatchProcessingPipeline, BatchProcessingResult } from './batch-processing-pipeline'

describe('BatchProcessingPipeline', () => {
    describe('static methods', () => {
        it('should create pipeline with success results using of()', async () => {
            const values = [{ test: 'data1' }, { test: 'data2' }]
            const pipeline = BatchProcessingPipeline.of(values)

            const results = await pipeline.unwrap()
            expect(results).toEqual([success({ test: 'data1' }), success({ test: 'data2' })])
        })

        it('should create pipeline with empty array', async () => {
            const pipeline = BatchProcessingPipeline.of([])

            const results = await pipeline.unwrap()
            expect(results).toEqual([])
        })
    })

    describe('pipe() - batch operations', () => {
        it('should execute batch step on all successful values', async () => {
            const values = [{ count: 1 }, { count: 2 }, { count: 3 }]
            const batchStep = (items: typeof values) => {
                return Promise.resolve(items.map((item) => success({ count: item.count * 2 })))
            }

            const results = await BatchProcessingPipeline.of(values).pipe(batchStep).unwrap()

            expect(results).toEqual([success({ count: 2 }), success({ count: 4 }), success({ count: 6 })])
        })

        it('should preserve non-success results and only process successful ones', async () => {
            const pipeline = new BatchProcessingPipeline<{ count: number }>(
                Promise.resolve([
                    success({ count: 1 }),
                    drop('dropped item'),
                    success({ count: 3 }),
                    dlq('dlq item', new Error('test error')),
                ])
            )

            const batchStep = (items: { count: number }[]) => {
                // Should only receive successful items
                expect(items).toEqual([{ count: 1 }, { count: 3 }])
                return Promise.resolve(items.map((item) => success({ count: item.count * 2 })))
            }

            const results = await pipeline.pipe(batchStep).unwrap()

            expect(results).toEqual([
                success({ count: 2 }),
                drop('dropped item'),
                success({ count: 6 }),
                dlq('dlq item', new Error('test error')),
            ])
        })

        it('should handle empty successful values array', async () => {
            const pipeline = new BatchProcessingPipeline<any>(
                Promise.resolve([
                    drop('dropped item 1'),
                    redirect('redirected item', 'overflow-topic'),
                    dlq('dlq item', new Error('test error')),
                ])
            )

            const batchStep = jest.fn((items: any[]) => {
                return Promise.resolve(items.map((item) => success(item)))
            })

            const results = await pipeline.pipe(batchStep).unwrap()

            expect(batchStep).not.toHaveBeenCalled()
            expect(results).toEqual([
                drop('dropped item 1'),
                redirect('redirected item', 'overflow-topic'),
                dlq('dlq item', new Error('test error')),
            ])
        })

        it('should chain multiple batch operations', async () => {
            const values = [{ value: 1 }, { value: 2 }]

            const step1 = (items: { value: number }[]) => {
                return Promise.resolve(items.map((item) => success({ value: item.value + 10 })))
            }

            const step2 = (items: { value: number }[]) => {
                return Promise.resolve(items.map((item) => success({ value: item.value * 2 })))
            }

            const results = await BatchProcessingPipeline.of(values).pipe(step1).pipe(step2).unwrap()

            expect(results).toEqual([success({ value: 22 }), success({ value: 24 })])
        })
    })

    describe('pipeConcurrently() - concurrent individual processing', () => {
        it('should process each item concurrently', async () => {
            const values = [{ count: 1 }, { count: 2 }, { count: 3 }]
            const stepConstructor = jest.fn(async (item: { count: number }) => {
                await new Promise((resolve) => setTimeout(resolve, 1))
                return success({ count: item.count * 2 })
            })

            const results = await BatchProcessingPipeline.of(values).pipeConcurrently(stepConstructor).unwrap()

            expect(results).toEqual([success({ count: 2 }), success({ count: 4 }), success({ count: 6 })])
            expect(stepConstructor).toHaveBeenCalledTimes(3)
        })

        it('should preserve order despite concurrent execution', async () => {
            const values = [{ delay: 30 }, { delay: 10 }, { delay: 20 }]
            const stepConstructor = async (item: { delay: number }) => {
                await new Promise((resolve) => setTimeout(resolve, item.delay))
                return success({ processed: item.delay })
            }

            const results = await BatchProcessingPipeline.of(values).pipeConcurrently(stepConstructor).unwrap()

            expect(results).toEqual([
                success({ processed: 30 }),
                success({ processed: 10 }),
                success({ processed: 20 }),
            ])
        })

        it('should preserve non-success results without processing them', async () => {
            const pipeline = new BatchProcessingPipeline<{ count: number }>(
                Promise.resolve([
                    success({ count: 1 }),
                    drop('dropped item'),
                    success({ count: 3 }),
                    redirect('redirected item', 'overflow-topic'),
                ])
            )

            const stepConstructor = jest.fn((item: { count: number }) => {
                return Promise.resolve(success({ count: item.count * 2 }))
            })

            const results = await pipeline.pipeConcurrently(stepConstructor).unwrap()

            expect(results).toEqual([
                success({ count: 2 }),
                drop('dropped item'),
                success({ count: 6 }),
                redirect('redirected item', 'overflow-topic'),
            ])
            expect(stepConstructor).toHaveBeenCalledTimes(2)
            expect(stepConstructor).toHaveBeenCalledWith({ count: 1 })
            expect(stepConstructor).toHaveBeenCalledWith({ count: 3 })
        })

        it('should handle individual step failures', async () => {
            const values = [{ count: 1 }, { count: 2 }, { count: 3 }]
            const stepConstructor = (item: { count: number }) => {
                if (item.count === 2) {
                    return Promise.resolve(drop('item 2 dropped'))
                }
                return Promise.resolve(success({ count: item.count * 2 }))
            }

            const results = await BatchProcessingPipeline.of(values).pipeConcurrently(stepConstructor).unwrap()

            expect(results).toEqual([success({ count: 2 }), drop('item 2 dropped'), success({ count: 6 })])
        })

        it('should handle mixed result types from individual processing', async () => {
            const values = [{ id: 1 }, { id: 2 }, { id: 3 }, { id: 4 }]
            const stepConstructor = (item: { id: number }) => {
                switch (item.id) {
                    case 1:
                        return Promise.resolve(success({ processed: item.id }))
                    case 2:
                        return Promise.resolve(drop('item 2 dropped'))
                    case 3:
                        return Promise.resolve(redirect('item 3 redirected', 'overflow-topic'))
                    case 4:
                        return Promise.resolve(dlq('item 4 failed', new Error('processing error')))
                    default:
                        return Promise.resolve(success({ processed: item.id }))
                }
            }

            const results = await BatchProcessingPipeline.of(values).pipeConcurrently(stepConstructor).unwrap()

            expect(results).toEqual([
                success({ processed: 1 }),
                drop('item 2 dropped'),
                redirect('item 3 redirected', 'overflow-topic'),
                dlq('item 4 failed', new Error('processing error')),
            ])
        })

        it('should chain pipeConcurrently operations', async () => {
            const values = [{ value: 1 }, { value: 2 }]

            const step1 = (item: { value: number }) => {
                return Promise.resolve(success({ value: item.value + 10 }))
            }

            const step2 = (item: { value: number }) => {
                return Promise.resolve(success({ value: item.value * 2 }))
            }

            const results = await BatchProcessingPipeline.of(values)
                .pipeConcurrently(step1)
                .pipeConcurrently(step2)
                .unwrap()

            expect(results).toEqual([success({ value: 22 }), success({ value: 24 })])
        })
    })

    describe('mixed operations', () => {
        it('should chain pipe and pipeConcurrently operations', async () => {
            const values = [{ count: 1 }, { count: 2 }, { count: 3 }]

            // First batch operation: double all values
            const batchStep = (items: { count: number }[]) => {
                return Promise.resolve(items.map((item) => success({ count: item.count * 2 })))
            }

            // Then individual operation: add 10 to each
            const individualStep = (item: { count: number }) => {
                return Promise.resolve(success({ count: item.count + 10 }))
            }

            const results = await BatchProcessingPipeline.of(values)
                .pipe(batchStep)
                .pipeConcurrently(individualStep)
                .unwrap()

            expect(results).toEqual([success({ count: 12 }), success({ count: 14 }), success({ count: 16 })])
        })

        it('should handle failures in mixed operations', async () => {
            const values = [{ name: 'a' }, { name: 'drop' }, { name: 'c' }, { name: 'dlq' }]

            // Batch operation that drops one item
            const batchStep = (items: { name: string }[]): Promise<BatchProcessingResult<{ name: string }>> => {
                return Promise.resolve(
                    items.map((item) => {
                        if (item.name === 'drop') {
                            return drop('batch dropped item')
                        }
                        return success({ name: item.name + '-batch' })
                    })
                )
            }

            // Individual operation that fails one item
            const individualStep = (item: { name: string }) => {
                if (item.name === 'dlq-batch') {
                    return Promise.resolve(dlq('individual failed item', new Error('processing error')))
                }
                return Promise.resolve(success({ name: item.name + '-individual' }))
            }

            const results = await BatchProcessingPipeline.of(values)
                .pipe(batchStep)
                .pipeConcurrently(individualStep)
                .unwrap()

            expect(results).toEqual([
                success({ name: 'a-batch-individual' }),
                drop('batch dropped item'), // Preserved from batch step
                success({ name: 'c-batch-individual' }),
                dlq('individual failed item', new Error('processing error')), // dlq-batch -> DLQ'd
            ])
        })
    })

    describe('error handling', () => {
        it('should propagate errors from batch operations', async () => {
            const values = [{ count: 1 }]
            const errorStep = () => {
                return Promise.reject(new Error('Batch step failed'))
            }

            await expect(BatchProcessingPipeline.of(values).pipe(errorStep).unwrap()).rejects.toThrow(
                'Batch step failed'
            )
        })

        it('should propagate errors from concurrent operations', async () => {
            const values = [{ count: 1 }]
            const errorStep = () => {
                return Promise.reject(new Error('Concurrent step failed'))
            }

            await expect(BatchProcessingPipeline.of(values).pipeConcurrently(errorStep).unwrap()).rejects.toThrow(
                'Concurrent step failed'
            )
        })

        it('should handle partial failures in concurrent operations', async () => {
            const values = [{ count: 1 }, { count: 2 }, { count: 3 }]
            const stepConstructor = (item: { count: number }) => {
                if (item.count === 2) {
                    return Promise.reject(new Error('Item 2 failed'))
                }
                return Promise.resolve(success({ count: item.count * 2 }))
            }

            await expect(BatchProcessingPipeline.of(values).pipeConcurrently(stepConstructor).unwrap()).rejects.toThrow(
                'Item 2 failed'
            )
        })
    })

    describe('type safety', () => {
        it('should maintain type safety through transformations', async () => {
            interface Input1 {
                value: number
            }
            interface Input2 {
                doubled: number
            }

            const step1 = (items: Input1[]) => {
                return Promise.resolve(items.map((item) => success({ doubled: item.value * 2 })))
            }

            const step2 = (item: Input2) => {
                return Promise.resolve(success({ final: `doubled: ${item.doubled}` }))
            }

            const results = await BatchProcessingPipeline.of([{ value: 5 }, { value: 10 }])
                .pipe(step1)
                .pipeConcurrently(step2)
                .unwrap()

            expect(results).toEqual([success({ final: 'doubled: 10' }), success({ final: 'doubled: 20' })])
        })
    })
})

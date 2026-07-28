import {withRetry} from '../src/retry'

describe('withRetry', () => {
  const delays: number[] = []
  const sleep = async (ms: number): Promise<void> => {
    delays.push(ms)
  }

  beforeEach(() => {
    delays.length = 0
  })

  test('does not retry an operation that succeeds', async () => {
    const operation = jest.fn().mockResolvedValue('files')

    await expect(withRetry(operation, {attempts: 3, baseDelayMs: 10, sleep})).resolves.toBe('files')
    expect(operation).toHaveBeenCalledTimes(1)
    expect(delays).toEqual([])
  })

  test('retries transient failures with exponential backoff and returns the eventual result', async () => {
    const onRetry = jest.fn()
    const operation = jest
      .fn()
      .mockRejectedValueOnce(new Error('Connect Timeout Error'))
      .mockRejectedValueOnce(new Error('Connect Timeout Error'))
      .mockResolvedValue('files')

    await expect(withRetry(operation, {attempts: 3, baseDelayMs: 10, onRetry, sleep})).resolves.toBe('files')
    expect(operation).toHaveBeenCalledTimes(3)
    expect(delays).toEqual([10, 20])
    expect(onRetry).toHaveBeenCalledTimes(2)
  })

  test('throws the last error once attempts are exhausted', async () => {
    const operation = jest
      .fn()
      .mockRejectedValueOnce(new Error('first failure'))
      .mockRejectedValue(new Error('last failure'))

    await expect(withRetry(operation, {attempts: 2, baseDelayMs: 10, sleep})).rejects.toThrow('last failure')
    expect(operation).toHaveBeenCalledTimes(2)
    expect(delays).toEqual([10])
  })
})

import { mergeUserProperties } from '../merge-user-properties'

describe('Amplitude - Merge user properties', () => {
  it('should work without crashing', () => {
    const result = mergeUserProperties({ a: 1 })
    expect(result).toEqual({ a: 1 })
  })

  it('should merge two first level props', () => {
    const a = { a: 1 }
    const b = { b: 'two' }
    const result = mergeUserProperties(a, b)
    expect(result).toEqual({ a: 1, b: 'two' })
  })

  it('should support set and setOnce explicitly', () => {
    const a = { a: 1, $set: { a: 1 }, $setOnce: { aa: 11 } }
    const b = { b: 'two', $set: { b: 'two' }, $setOnce: { bb: 'twotwo' } }
    const result = mergeUserProperties(a, b)
    expect(result).toEqual({ a: 1, b: 'two', $set: { a: 1, b: 'two' }, $setOnce: { aa: 11, bb: 'twotwo' } })
  })

  it('should support merging existing flat props', () => {
    const a = { $set: { a: 1 }, $setOnce: { aa: 11 } }
    const b = { $set: { b: 'two' }, $setOnce: { bb: 'twotwo' } }
    const c = { a: 1, b: 2 }
    const result = mergeUserProperties(a, b, c)
    expect(result).toEqual({ a: 1, b: 2, $set: { a: 1, b: 'two' }, $setOnce: { aa: 11, bb: 'twotwo' } })
  })
})

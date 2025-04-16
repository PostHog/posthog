import { formatSessionId } from '../convert-timestamp'

describe('Amplitude - Convert timestamp - format session_id', () => {
  it('should convert string to number', () => {
    const result = formatSessionId('987654321')
    expect(result).toEqual(987654321)
  })

  it('should return number as it is', () => {
    const result = formatSessionId(987654321)
    expect(result).toEqual(987654321)
  })

  it('should convert string to unix timestamp', () => {
    const result = formatSessionId('2000-10-31T01:30:00.000-05:00')
    expect(result).toEqual(972973800000)
  })

  it('should convert string to unix timestamp', () => {
    const result = formatSessionId('2021-06-08')
    expect(result).toEqual(1623110400000)
  })
})

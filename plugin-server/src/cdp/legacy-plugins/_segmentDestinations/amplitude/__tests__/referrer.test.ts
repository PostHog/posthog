import { convertReferrerProperty } from '../referrer'

describe('Amplitude - referrer utility', () => {
  it('should run without exploding', () => {
    const result = convertReferrerProperty({})
    expect(result).toEqual({})
  })

  it('should append $set and $setOnce when referrer is provided and user_properties exists', () => {
    const user_properties = {
      a: 1,
      b: 'two',
      c: {
        d: true
      }
    }

    const referrer = 'some ref'

    const payload = {
      user_properties,
      referrer
    }

    const result = convertReferrerProperty(payload)
    expect(result).toEqual({
      $set: {
        referrer
      },
      $setOnce: {
        initial_referrer: referrer
      }
    })
  })

  it('should create a user_properties when referrer is provided and there is not an existing', () => {
    const referrer = 'some ref 2'

    const result = convertReferrerProperty({ referrer })
    expect(result).toEqual({
      $set: {
        referrer
      },
      $setOnce: {
        initial_referrer: referrer
      }
    })
  })
})

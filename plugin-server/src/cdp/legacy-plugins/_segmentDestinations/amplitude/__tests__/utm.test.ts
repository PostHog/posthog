import { convertUTMProperties } from '../utm'

describe('Amplitude - utm utility', () => {
  it('should run without exploding', () => {
    const result = convertUTMProperties({})
    expect(result).toEqual({})
  })

  it('should append $set and $setOnce when utm is provided and user_properties exists', () => {
    const user_properties = {
      a: 1,
      b: 'two',
      c: {
        d: true
      }
    }

    const utm_properties = {
      utm_source: 'source',
      utm_medium: 'medium',
      utm_campaign: 'campaign',
      utm_term: 'term',
      utm_content: 'content'
    }

    const payload = {
      user_properties,
      utm_properties
    }

    const result = convertUTMProperties(payload)
    expect(result).toEqual({
      $set: {
        ...utm_properties
      },
      $setOnce: {
        initial_utm_source: 'source',
        initial_utm_medium: 'medium',
        initial_utm_campaign: 'campaign',
        initial_utm_term: 'term',
        initial_utm_content: 'content'
      }
    })
  })

  it('should create a user_properties when utm is provided and there is not an existing', () => {
    const utm_properties = {
      utm_source: 'source',
      utm_medium: 'medium',
      utm_campaign: 'campaign',
      utm_term: 'term',
      utm_content: 'content'
    }
    const result = convertUTMProperties({ utm_properties })
    expect(result).toEqual({
      $set: {
        ...utm_properties
      },
      $setOnce: {
        initial_utm_source: 'source',
        initial_utm_medium: 'medium',
        initial_utm_campaign: 'campaign',
        initial_utm_term: 'term',
        initial_utm_content: 'content'
      }
    })
  })
})

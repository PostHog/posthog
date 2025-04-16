import { parseUserAgentProperties } from '../user-agent'

describe('amplitude - custom user agent parsing', () => {
  it('should parse custom user agent', () => {
    //This is borrowed from amplitude tests so we know its parsable:
    // https://github.com/amplitude/ua-parser-js/blob/master/test/device-test.json#L138
    const userAgent =
      '"Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/74.0.0.0 Safari/537.36"'

    const userAgentData = {
      model: 'TAB 2 A7',
      platformVersion: '5.0.1'
    }

    const result = parseUserAgentProperties(userAgent, userAgentData)

    expect(result).toEqual({
      device_manufacturer: undefined,
      os_name: 'Android',
      os_version: '5.0.1',
      device_model: 'TAB 2 A7',
      device_type: 'tablet'
    })
  })

  it('should parse custom user for desktop strings', () => {
    const userAgent =
      'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/93.0.4577.82 Safari/537.36'
    const result = parseUserAgentProperties(userAgent)
    expect(result).toEqual({
      device_manufacturer: undefined,
      device_model: 'Mac OS',
      device_type: undefined,
      os_name: 'Mac OS',
      os_version: '93'
    })
  })

  it('should return an empty object when there is no user agent', () => {
    const result = parseUserAgentProperties(undefined)
    expect(result).toEqual({})
  })

  it('should parse custom user agent and use userAgentData for os_version and device_model', () => {
    const userAgent =
      '"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36"'

    const userAgentData = {
      model: 'SM-J710FN',
      platformVersion: '12.6.1'
    }

    const result = parseUserAgentProperties(userAgent, userAgentData)

    expect(result).toEqual({
      device_manufacturer: undefined,
      device_model: 'SM-J710FN',
      device_type: undefined,
      os_name: 'Mac OS',
      os_version: '12.6.1'
    })
  })

  it('should parse custom user for iphone strings', () => {
    const userAgent =
      'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1'
    const result = parseUserAgentProperties(userAgent)
    expect(result).toEqual({
      device_manufacturer: 'Apple',
      device_model: 'iPhone',
      device_type: 'mobile',
      os_name: 'iOS',
      os_version: '16'
    })
  })
})

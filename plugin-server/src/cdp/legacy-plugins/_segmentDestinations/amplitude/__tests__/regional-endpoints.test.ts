import { endpoints, getEndpointByRegion } from '../regional-endpoints'

describe('Amplitude - Regional endpoints', () => {
  it('should set region to north_america when no region is provided', () => {
    const result = getEndpointByRegion('httpapi')
    expect(result).toEqual(endpoints.httpapi.north_america)
  })
  it('should return the North American endpoint', () => {
    const result = getEndpointByRegion('httpapi', 'north_america')
    expect(result).toEqual(endpoints.httpapi.north_america)
  })
  it('should return the European endpoint', () => {
    const result = getEndpointByRegion('httpapi', 'europe')
    expect(result).toEqual(endpoints.httpapi.europe)
  })
  it('should return the North American endpoint when an invalid region is provided', () => {
    const result = getEndpointByRegion('httpapi', 'NONE')
    expect(result).toEqual(endpoints.httpapi.north_america)
  })
  it('should return the correct endpoints', () => {
    expect(endpoints).toMatchInlineSnapshot(`
      Object {
        "batch": Object {
          "europe": "https://api.eu.amplitude.com/batch",
          "north_america": "https://api2.amplitude.com/batch",
        },
        "deletions": Object {
          "europe": "https://analytics.eu.amplitude.com/api/2/deletions/users",
          "north_america": "https://amplitude.com/api/2/deletions/users",
        },
        "groupidentify": Object {
          "europe": "https://api.eu.amplitude.com/groupidentify",
          "north_america": "https://api2.amplitude.com/groupidentify",
        },
        "httpapi": Object {
          "europe": "https://api.eu.amplitude.com/2/httpapi",
          "north_america": "https://api2.amplitude.com/2/httpapi",
        },
        "identify": Object {
          "europe": "https://api.eu.amplitude.com/identify",
          "north_america": "https://api2.amplitude.com/identify",
        },
        "usermap": Object {
          "europe": "https://api.eu.amplitude.com/usermap",
          "north_america": "https://api.amplitude.com/usermap",
        },
        "usersearch": Object {
          "europe": "https://analytics.eu.amplitude.com/api/2/usersearch",
          "north_america": "https://amplitude.com/api/2/usersearch",
        },
      }
    `)
  })
})

export const endpoints = {
  batch: {
    north_america: 'https://api2.amplitude.com/batch',
    europe: 'https://api.eu.amplitude.com/batch'
  },
  deletions: {
    north_america: 'https://amplitude.com/api/2/deletions/users',
    europe: 'https://analytics.eu.amplitude.com/api/2/deletions/users'
  },
  httpapi: {
    north_america: 'https://api2.amplitude.com/2/httpapi',
    europe: 'https://api.eu.amplitude.com/2/httpapi'
  },
  identify: {
    north_america: 'https://api2.amplitude.com/identify',
    europe: 'https://api.eu.amplitude.com/identify'
  },
  groupidentify: {
    north_america: 'https://api2.amplitude.com/groupidentify',
    europe: 'https://api.eu.amplitude.com/groupidentify'
  },
  usermap: {
    north_america: 'https://api.amplitude.com/usermap',
    europe: 'https://api.eu.amplitude.com/usermap'
  },
  usersearch: {
    north_america: 'https://amplitude.com/api/2/usersearch',
    europe: 'https://analytics.eu.amplitude.com/api/2/usersearch'
  }
}

type Region = 'north_america' | 'europe'

/**
 * Retrieves Amplitude API endpoints for a given region. If the region
 * provided does not exist, the region defaults to 'north_america'.
 *
 * @param endpoint name of the API endpoint
 * @param region data residency region
 * @returns regional API endpoint
 */
export function getEndpointByRegion(endpoint: keyof typeof endpoints, region?: string): string {
  return endpoints[endpoint][region as Region] ?? endpoints[endpoint]['north_america']
}

export default endpoints

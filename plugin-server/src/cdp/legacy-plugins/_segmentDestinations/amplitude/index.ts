import type { DestinationDefinition } from '@segment/actions-core'
import { defaultValues } from '@segment/actions-core'
import identifyUser from './identifyUser'
import logEvent from './logEvent'
import mapUser from './mapUser'
import groupIdentifyUser from './groupIdentifyUser'
import logPurchase from './logPurchase'
import type { Settings } from './generated-types'
import { getEndpointByRegion } from './regional-endpoints'

import logEventV2 from './logEventV2'

/** used in the quick setup */
const presets: DestinationDefinition['presets'] = [
  {
    name: 'Track Calls',
    subscribe: 'type = "track" and event != "Order Completed"',
    partnerAction: 'logEventV2',
    mapping: defaultValues(logEventV2.fields),
    type: 'automatic'
  },
  {
    name: 'Order Completed Calls',
    subscribe: 'type = "track" and event = "Order Completed"',
    partnerAction: 'logPurchase',
    mapping: defaultValues(logPurchase.fields),
    type: 'automatic'
  },
  {
    name: 'Page Calls',
    subscribe: 'type = "page"',
    partnerAction: 'logEventV2',
    mapping: {
      ...defaultValues(logEventV2.fields),
      event_type: {
        '@template': 'Viewed {{name}}'
      }
    },
    type: 'automatic'
  },
  {
    name: 'Screen Calls',
    subscribe: 'type = "screen"',
    partnerAction: 'logEventV2',
    mapping: {
      ...defaultValues(logEventV2.fields),
      event_type: {
        '@template': 'Viewed {{name}}'
      }
    },
    type: 'automatic'
  },
  {
    name: 'Identify Calls',
    subscribe: 'type = "identify"',
    partnerAction: 'identifyUser',
    mapping: defaultValues(identifyUser.fields),
    type: 'automatic'
  },
  {
    name: 'Browser Session Tracking',
    subscribe: 'type = "track" or type = "identify" or type = "group" or type = "page" or type = "alias"',
    partnerAction: 'sessionId',
    mapping: {},
    type: 'automatic'
  }
]

const destination: DestinationDefinition<Settings> = {
  name: 'Actions Amplitude',
  slug: 'actions-amplitude',
  mode: 'cloud',
  authentication: {
    scheme: 'custom',
    fields: {
      apiKey: {
        label: 'API Key',
        description: 'Amplitude project API key. You can find this key in the "General" tab of your Amplitude project.',
        type: 'string',
        required: true
      },
      secretKey: {
        label: 'Secret Key',
        description:
          'Amplitude project secret key. You can find this key in the "General" tab of your Amplitude project.',
        type: 'string',
        required: true
      },
      endpoint: {
        label: 'Endpoint Region',
        description: 'The region to send your data.',
        type: 'string',
        format: 'text',
        choices: [
          {
            label: 'North America',
            value: 'north_america'
          },
          {
            label: 'Europe',
            value: 'europe'
          }
        ],
        default: 'north_america'
      }
    },
    testAuthentication: (request, { settings }) => {
      // Note: Amplitude has some apis that use basic auth (like this one)
      // and others that use custom auth in the request body
      const endpoint = getEndpointByRegion('usersearch', settings.endpoint)
      return request(`${endpoint}?user=testUser@example.com`, {
        username: settings.apiKey,
        password: settings.secretKey
      })
    }
  },
  onDelete: async (request, { settings, payload }) => {
    return request(getEndpointByRegion('deletions', settings.endpoint), {
      username: settings.apiKey,
      password: settings.secretKey,
      method: 'post',
      json: {
        user_ids: [payload.userId],
        requester: 'segment'
      }
    })
  },
  presets,
  actions: {
    logEvent,
    identifyUser,
    mapUser,
    groupIdentifyUser,
    logPurchase,
    logEventV2
  }
}

export default destination

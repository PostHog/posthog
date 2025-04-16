import { ActionDefinition, omit, removeUndefined } from '@segment/actions-core'
import dayjs from 'dayjs'
import compact from '../compact'
import { eventSchema } from '../event-schema'
import type { Settings } from '../generated-types'
import { getEndpointByRegion } from '../regional-endpoints'
import { parseUserAgentProperties } from '../user-agent'
import type { Payload } from './generated-types'
import { formatSessionId } from '../convert-timestamp'
import { userAgentData } from '../properties'

export interface AmplitudeEvent extends Omit<Payload, 'products' | 'time' | 'session_id'> {
  library?: string
  time?: number
  session_id?: number
  options?: {
    min_id_length: number
  }
}

const revenueKeys = ['revenue', 'price', 'productId', 'quantity', 'revenueType']

const action: ActionDefinition<Settings, Payload> = {
  title: 'Log Event V2',
  description: 'Send an event to Amplitude',
  defaultSubscription: 'type = "track"',
  fields: {
    ...eventSchema,
    products: {
      label: 'Products',
      description: 'The list of products purchased.',
      type: 'object',
      multiple: true,
      additionalProperties: true,
      properties: {
        price: {
          label: 'Price',
          type: 'number',
          description:
            'The price of the item purchased. Required for revenue data if the revenue field is not sent. You can use negative values to indicate refunds.'
        },
        quantity: {
          label: 'Quantity',
          type: 'integer',
          description: 'The quantity of the item purchased. Defaults to 1 if not specified.'
        },
        revenue: {
          label: 'Revenue',
          type: 'number',
          description:
            'Revenue = price * quantity. If you send all 3 fields of price, quantity, and revenue, then (price * quantity) will be used as the revenue value. You can use negative values to indicate refunds.'
        },
        productId: {
          label: 'Product ID',
          type: 'string',
          description:
            'An identifier for the item purchased. You must send a price and quantity or revenue with this field.'
        },
        revenueType: {
          label: 'Revenue Type',
          type: 'string',
          description:
            'The type of revenue for the item purchased. You must send a price and quantity or revenue with this field.'
        }
      },
      default: {
        '@arrayPath': [
          '$.properties.products',
          {
            price: {
              '@path': 'price'
            },
            revenue: {
              '@path': 'revenue'
            },
            quantity: {
              '@path': 'quantity'
            },
            productId: {
              '@path': 'productId'
            },
            revenueType: {
              '@path': 'revenueType'
            }
          }
        ]
      }
    },
    setOnce: {
      label: 'Set Once',
      description: 'The following fields will only be set as user properties if they do not already have a value.',
      type: 'object',
      additionalProperties: true,
      properties: {
        initial_referrer: {
          label: 'Initial Referrer',
          type: 'string',
          description: 'The referrer of the web request.'
        },
        initial_utm_source: {
          label: 'Initial UTM Source',
          type: 'string'
        },
        initial_utm_medium: {
          label: 'Initial UTM Medium',
          type: 'string'
        },
        initial_utm_campaign: {
          label: 'Initial UTM Campaign',
          type: 'string'
        },
        initial_utm_term: {
          label: 'Initial UTM Term',
          type: 'string'
        },
        initial_utm_content: {
          label: 'Initial UTM Content',
          type: 'string'
        }
      },
      default: {
        initial_referrer: { '@path': '$.context.page.referrer' },
        initial_utm_source: { '@path': '$.context.campaign.source' },
        initial_utm_medium: { '@path': '$.context.campaign.medium' },
        initial_utm_campaign: { '@path': '$.context.campaign.name' },
        initial_utm_term: { '@path': '$.context.campaign.term' },
        initial_utm_content: { '@path': '$.context.campaign.content' }
      }
    },
    setAlways: {
      label: 'Set Always',
      description: 'The following fields will be set as user properties for every event.',
      type: 'object',
      additionalProperties: true,
      properties: {
        referrer: {
          label: 'Referrer',
          type: 'string'
        },
        utm_source: {
          label: 'UTM Source',
          type: 'string'
        },
        utm_medium: {
          label: 'UTM Medium',
          type: 'string'
        },
        utm_campaign: {
          label: 'UTM Campaign',
          type: 'string'
        },
        utm_term: {
          label: 'UTM Term',
          type: 'string'
        },
        utm_content: {
          label: 'UTM Content',
          type: 'string'
        }
      },
      default: {
        referrer: { '@path': '$.context.page.referrer' },
        utm_source: { '@path': '$.context.campaign.source' },
        utm_medium: { '@path': '$.context.campaign.medium' },
        utm_campaign: { '@path': '$.context.campaign.name' },
        utm_term: { '@path': '$.context.campaign.term' },
        utm_content: { '@path': '$.context.campaign.content' }
      }
    },
    add: {
      label: 'Add',
      description:
        "Increment a user property by a number with add. If the user property doesn't have a value set yet, it's initialized to 0.",
      type: 'object',
      additionalProperties: true,
      defaultObjectUI: 'keyvalue'
    },
    use_batch_endpoint: {
      label: 'Use Batch Endpoint',
      description:
        "If true, events are sent to Amplitude's `batch` endpoint rather than their `httpapi` events endpoint. Enabling this setting may help reduce 429s – or throttling errors – from Amplitude. More information about Amplitude's throttling is available in [their docs](https://developers.amplitude.com/docs/batch-event-upload-api#429s-in-depth).",
      type: 'boolean',
      default: false
    },
    userAgent: {
      label: 'User Agent',
      type: 'string',
      description: 'The user agent of the device sending the event.',
      default: {
        '@path': '$.context.userAgent'
      }
    },
    userAgentParsing: {
      label: 'User Agent Parsing',
      type: 'boolean',
      description:
        'Enabling this setting will set the Device manufacturer, Device Model and OS Name properties based on the user agent string provided in the userAgent field.',
      default: true
    },
    includeRawUserAgent: {
      label: 'Include Raw User Agent',
      type: 'boolean',
      description:
        'Enabling this setting will send user_agent based on the raw user agent string provided in the userAgent field',
      default: false
    },
    min_id_length: {
      label: 'Minimum ID Length',
      description:
        'Amplitude has a default minimum id length of 5 characters for user_id and device_id fields. This field allows the minimum to be overridden to allow shorter id lengths.',
      allowNull: true,
      type: 'integer'
    },
    userAgentData
  },
  perform: (request, { payload, settings }) => {
    const {
      time,
      session_id,
      userAgent,
      userAgentParsing,
      includeRawUserAgent,
      userAgentData,
      min_id_length,
      library,
      setOnce,
      setAlways,
      add,
      ...rest
    } = omit(payload, revenueKeys)
    const properties = rest as AmplitudeEvent
    let options

    if (properties.platform) {
      properties.platform = properties.platform.replace(/ios/i, 'iOS').replace(/android/i, 'Android')
    }

    if (library === 'analytics.js' && !properties.platform) {
      properties.platform = 'Web'
    }

    if (time && dayjs.utc(time).isValid()) {
      properties.time = dayjs.utc(time).valueOf()
    }

    if (session_id && dayjs.utc(session_id).isValid()) {
      properties.session_id = formatSessionId(session_id)
    }

    if (min_id_length && min_id_length > 0) {
      options = { min_id_length }
    }

    const setUserProperties = (
      name: '$setOnce' | '$set' | '$add',
      obj: Payload['setOnce'] | Payload['setAlways'] | Payload['add']
    ) => {
      if (compact(obj)) {
        properties.user_properties = { ...properties.user_properties, [name]: obj }
      }
    }

    setUserProperties('$setOnce', setOnce)
    setUserProperties('$set', setAlways)
    setUserProperties('$add', add)

    const events: AmplitudeEvent[] = [
      {
        // Conditionally parse user agent using amplitude's library
        ...(userAgentParsing && parseUserAgentProperties(userAgent, userAgentData)),
        ...(includeRawUserAgent && { user_agent: userAgent }),
        // Make sure any top-level properties take precedence over user-agent properties
        ...removeUndefined(properties),
        library: 'segment'
      }
    ]

    const endpoint = getEndpointByRegion(payload.use_batch_endpoint ? 'batch' : 'httpapi', settings.endpoint)

    return request(endpoint, {
      method: 'post',
      json: {
        api_key: settings.apiKey,
        events,
        options
      }
    })
  }
}

export default action

import { omit, removeUndefined } from '@segment/actions-core'
import dayjs from '../../../lib/dayjs'
import { eventSchema } from '../event-schema'
import type { ActionDefinition } from '@segment/actions-core'
import type { Settings } from '../generated-types'
import type { Payload } from './generated-types'
import { convertUTMProperties } from '../utm'
import { convertReferrerProperty } from '../referrer'
import { mergeUserProperties } from '../merge-user-properties'
import { parseUserAgentProperties } from '../user-agent'
import { getEndpointByRegion } from '../regional-endpoints'
import { formatSessionId } from '../convert-timestamp'
import { userAgentData } from '../properties'

export interface AmplitudeEvent extends Omit<Payload, 'products' | 'trackRevenuePerProduct' | 'time' | 'session_id'> {
  library?: string
  time?: number
  session_id?: number
  options?: {
    min_id_length: number
  }
}

const revenueKeys = ['revenue', 'price', 'productId', 'quantity', 'revenueType']

interface EventRevenue {
  revenue?: number
  price?: number
  productId?: string
  quantity?: number
  revenueType?: string
}

function getRevenueProperties(payload: EventRevenue): EventRevenue {
  let revenue = payload.revenue
  if (typeof payload.quantity === 'number' && typeof payload.price === 'number') {
    revenue = payload.quantity * payload.price
  }

  if (!revenue) {
    return {}
  }

  return {
    revenue,
    revenueType: payload.revenueType ?? 'Purchase',
    quantity: typeof payload.quantity === 'number' ? Math.round(payload.quantity) : undefined,
    price: payload.price,
    productId: payload.productId
  }
}

const action: ActionDefinition<Settings, Payload> = {
  title: 'Log Purchase',
  description: 'Send an event to Amplitude.',
  defaultSubscription: 'type = "track"',
  fields: {
    trackRevenuePerProduct: {
      label: 'Track Revenue Per Product',
      description:
        'When enabled, track revenue with each product within the event. When disabled, track total revenue once for the event.',
      type: 'boolean',
      default: false
    },
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
            'Revenue = price * quantity. If you send all 3 fields of price, quantity, and revenue, then (price * quantity) will be used as the revenue value. You can use negative values to indicate refunds.',
          depends_on: {
            match: 'any',
            conditions: [
              {
                fieldKey: 'price',
                operator: 'is',
                value: ''
              },
              {
                fieldKey: 'quantity',
                operator: 'is',
                value: ''
              }
            ]
          }
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
        'Enabling this setting will set the Device manufacturer, Device Model and OS Name properties based on the user agent string provided in the userAgent field',
      default: true
    },
    includeRawUserAgent: {
      label: 'Include Raw User Agent',
      type: 'boolean',
      description:
        'Enabling this setting will send user_agent based on the raw user agent string provided in the userAgent field',
      default: false
    },
    utm_properties: {
      label: 'UTM Properties',
      type: 'object',
      description: 'UTM Tracking Properties',
      properties: {
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
        utm_source: { '@path': '$.context.campaign.source' },
        utm_medium: { '@path': '$.context.campaign.medium' },
        utm_campaign: { '@path': '$.context.campaign.name' },
        utm_term: { '@path': '$.context.campaign.term' },
        utm_content: { '@path': '$.context.campaign.content' }
      }
    },
    referrer: {
      label: 'Referrer',
      type: 'string',
      description:
        'The referrer of the web request. Sent to Amplitude as both last touch “referrer” and first touch “initial_referrer”',
      default: {
        '@path': '$.context.page.referrer'
      }
    },
    min_id_length: {
      label: 'Minimum ID Length',
      description:
        'Amplitude has a default minimum id lenght of 5 characters for user_id and device_id fields. This field allows the minimum to be overridden to allow shorter id lengths.',
      allowNull: true,
      type: 'integer'
    },
    userAgentData
  },
  perform: (request, { payload, settings }) => {
    // Omit revenue properties initially because we will manually stitch those into events as prescribed
    const {
      products = [],
      trackRevenuePerProduct,
      time,
      session_id,
      userAgent,
      userAgentParsing,
      includeRawUserAgent,
      userAgentData,
      utm_properties,
      referrer,
      min_id_length,
      library,
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

    if (Object.keys(payload.utm_properties ?? {}).length || payload.referrer) {
      properties.user_properties = mergeUserProperties(
        convertUTMProperties({ utm_properties }),
        convertReferrerProperty({ referrer }),
        omit(properties.user_properties ?? {}, ['utm_properties', 'referrer'])
      )
    }

    if (min_id_length && min_id_length > 0) {
      options = { min_id_length }
    }

    const events: AmplitudeEvent[] = [
      {
        // Conditionally parse user agent using amplitude's library
        ...(userAgentParsing && parseUserAgentProperties(userAgent, userAgentData)),
        ...(includeRawUserAgent && { user_agent: userAgent }),
        // Make sure any top-level properties take precedence over user-agent properties
        ...removeUndefined(properties),
        // Conditionally track revenue with main event
        ...(products.length && trackRevenuePerProduct ? {} : getRevenueProperties(payload)),
        library: 'segment'
      }
    ]

    for (const product of products) {
      events.push({
        ...properties,
        // Or track revenue per product
        ...(trackRevenuePerProduct ? getRevenueProperties(product as EventRevenue) : {}),
        event_properties: product,
        event_type: 'Product Purchased',
        insert_id: properties.insert_id ? `${properties.insert_id}-${events.length + 1}` : undefined,
        library: 'segment'
      })
    }

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

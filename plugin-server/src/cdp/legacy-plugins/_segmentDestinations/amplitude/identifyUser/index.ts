import { ActionDefinition, omit, removeUndefined } from '@segment/actions-core'
import type { Settings } from '../generated-types'
import type { Payload } from './generated-types'
import { convertUTMProperties } from '../utm'
import { convertReferrerProperty } from '../referrer'
import { parseUserAgentProperties } from '../user-agent'
import { mergeUserProperties } from '../merge-user-properties'
import { AmplitudeEvent } from '../logEvent'
import { getEndpointByRegion } from '../regional-endpoints'
import { userAgentData } from '../properties'

const action: ActionDefinition<Settings, Payload> = {
  title: 'Identify User',
  description:
    'Set the user ID for a particular device ID or update user properties without sending an event to Amplitude.',
  defaultSubscription: 'type = "identify"',
  fields: {
    user_id: {
      label: 'User ID',
      type: 'string',
      allowNull: true,
      description:
        'A UUID (unique user ID) specified by you. **Note:** If you send a request with a user ID that is not in the Amplitude system yet, then the user tied to that ID will not be marked new until their first event. Required unless device ID is present.',
      default: {
        '@path': '$.userId'
      }
    },
    device_id: {
      label: 'Device ID',
      type: 'string',
      description:
        'A device specific identifier, such as the Identifier for Vendor (IDFV) on iOS. Required unless user ID is present.',
      default: {
        '@if': {
          exists: { '@path': '$.context.device.id' },
          then: { '@path': '$.context.device.id' },
          else: { '@path': '$.anonymousId' }
        }
      }
    },
    user_properties: {
      label: 'User Properties',
      type: 'object',
      description:
        'Additional data tied to the user in Amplitude. Each distinct value will show up as a user segment on the Amplitude dashboard. Object depth may not exceed 40 layers. **Note:** You can store property values in an array and date values are transformed into string values.',
      default: {
        '@path': '$.traits'
      }
    },
    groups: {
      label: 'Groups',
      type: 'object',
      description:
        "Groups of users for Amplitude's account-level reporting feature. Note: You can only track up to 5 groups. Any groups past that threshold will not be tracked. **Note:** This feature is only available to Amplitude Enterprise customers who have purchased the Amplitude Accounts add-on."
    },
    app_version: {
      label: 'App Version',
      type: 'string',
      description: 'Version of the app the user is on.',
      default: {
        '@path': '$.context.app.version'
      }
    },
    platform: {
      label: 'Platform',
      type: 'string',
      description: "The platform of the user's device.",
      default: {
        '@path': '$.context.device.type'
      }
    },
    os_name: {
      label: 'OS Name',
      type: 'string',
      description: "The mobile operating system or browser of the user's device.",
      default: {
        '@path': '$.context.os.name'
      }
    },
    os_version: {
      label: 'OS Version',
      type: 'string',
      description: "The version of the mobile operating system or browser of the user's device.",
      default: {
        '@path': '$.context.os.version'
      }
    },
    device_brand: {
      label: 'Device Brand',
      type: 'string',
      description: "The brand of user's the device.",
      default: {
        '@path': '$.context.device.brand'
      }
    },
    device_manufacturer: {
      label: 'Device Manufacturer',
      type: 'string',
      description: "The manufacturer of the user's device.",
      default: {
        '@path': '$.context.device.manufacturer'
      }
    },
    device_model: {
      label: 'Device Model',
      type: 'string',
      description: "The model of the user's device.",
      default: {
        '@path': '$.context.device.model'
      }
    },
    carrier: {
      label: 'Carrier',
      type: 'string',
      description: "The user's mobile carrier.",
      default: {
        '@path': '$.context.network.carrier'
      }
    },
    country: {
      label: 'Country',
      type: 'string',
      description: 'The country in which the user is located.',
      default: {
        '@path': '$.context.location.country'
      }
    },
    region: {
      label: 'Region',
      type: 'string',
      description: 'The geographical region in which the user is located.',
      default: {
        '@path': '$.context.location.region'
      }
    },
    city: {
      label: 'City',
      type: 'string',
      description: 'The city in which the user is located.',
      default: {
        '@path': '$.context.location.city'
      }
    },
    dma: {
      label: 'Designated Market Area',
      type: 'string',
      description: 'The Designated Market Area in which the user is located.'
    },
    language: {
      label: 'Language',
      type: 'string',
      description: 'Language the user has set on their device or browser.',
      default: {
        '@path': '$.context.locale'
      }
    },
    paying: {
      label: 'Is Paying',
      type: 'boolean',
      description: 'Whether the user is paying or not.'
    },
    start_version: {
      label: 'Initial Version',
      type: 'string',
      description: 'The version of the app the user was first on.'
    },
    insert_id: {
      label: 'Insert ID',
      type: 'string',
      description:
        'Amplitude will deduplicate subsequent events sent with this ID we have already seen before within the past 7 days. Amplitude recommends generating a UUID or using some combination of device ID, user ID, event type, event ID, and time.'
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
        'Amplitude has a default minimum id length of 5 characters for user_id and device_id fields. This field allows the minimum to be overridden to allow shorter id lengths.',
      allowNull: true,
      type: 'integer'
    },
    library: {
      label: 'Library',
      type: 'string',
      description: 'The name of the library that generated the event.',
      default: {
        '@path': '$.context.library.name'
      }
    },
    userAgentData
  },

  perform: (request, { payload, settings }) => {
    const {
      utm_properties,
      referrer,
      userAgent,
      userAgentParsing,
      includeRawUserAgent,
      userAgentData,
      min_id_length,
      library,
      ...rest
    } = payload

    let options
    const properties = rest as AmplitudeEvent

    if (properties.platform) {
      properties.platform = properties.platform.replace(/ios/i, 'iOS').replace(/android/i, 'Android')
    }

    if (library === 'analytics.js' && !properties.platform) {
      properties.platform = 'Web'
    }

    if (Object.keys(utm_properties ?? {}).length || referrer) {
      properties.user_properties = mergeUserProperties(
        omit(properties.user_properties ?? {}, ['utm_properties', 'referrer']),
        convertUTMProperties(payload),
        convertReferrerProperty(payload)
      )
    }

    if (min_id_length && min_id_length > 0) {
      options = JSON.stringify({ min_id_length })
    }

    const identification = JSON.stringify({
      // Conditionally parse user agent using amplitude's library
      ...(userAgentParsing && parseUserAgentProperties(userAgent, userAgentData)),
      ...(includeRawUserAgent && { user_agent: userAgent }),
      // Make sure any top-level properties take precedence over user-agent properties
      ...removeUndefined(properties),
      library: 'segment'
    })

    return request(getEndpointByRegion('identify', settings.endpoint), {
      method: 'post',
      body: new URLSearchParams({
        api_key: settings.apiKey,
        identification,
        options
      } as Record<string, string>)
    })
  }
}

export default action

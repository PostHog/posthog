import { InputField } from '@segment/actions-core'

/**
 * The common fields defined by Amplitude's events api
 * @see {@link https://developers.amplitude.com/docs/http-api-v2#keys-for-the-event-argument}
 */
export const eventSchema: Record<string, InputField> = {
  user_id: {
    label: 'User ID',
    type: 'string',
    allowNull: true,
    description:
      'A readable ID specified by you. Must have a minimum length of 5 characters. Required unless device ID is present. **Note:** If you send a request with a user ID that is not in the Amplitude system yet, then the user tied to that ID will not be marked new until their first event.',
    default: {
      '@path': '$.userId'
    }
  },
  device_id: {
    label: 'Device ID',
    type: 'string',
    description:
      'A device-specific identifier, such as the Identifier for Vendor on iOS. Required unless user ID is present. If a device ID is not sent with the event, it will be set to a hashed version of the user ID.',
    default: {
      '@if': {
        exists: { '@path': '$.context.device.id' },
        then: { '@path': '$.context.device.id' },
        else: { '@path': '$.anonymousId' }
      }
    }
  },
  event_type: {
    label: 'Event Type',
    type: 'string',
    description: 'A unique identifier for your event.',
    required: true,
    default: {
      '@path': '$.event'
    }
  },
  session_id: {
    label: 'Session ID',
    type: 'datetime',
    description:
      'The start time of the session, necessary if you want to associate events with a particular system. To use automatic Amplitude session tracking in browsers, enable Analytics 2.0 on your connected source.',
    default: {
      '@path': '$.integrations.Actions Amplitude.session_id'
    }
  },
  time: {
    label: 'Timestamp',
    type: 'datetime',
    description:
      'The timestamp of the event. If time is not sent with the event, it will be set to the request upload time.',
    default: {
      '@path': '$.timestamp'
    }
  },
  event_properties: {
    label: 'Event Properties',
    type: 'object',
    description:
      'An object of key-value pairs that represent additional data to be sent along with the event. You can store property values in an array, but note that Amplitude only supports one-dimensional arrays. Date values are transformed into string values. Object depth may not exceed 40 layers.',
    default: {
      '@path': '$.properties'
    }
  },
  user_properties: {
    label: 'User Properties',
    type: 'object',
    description:
      'An object of key-value pairs that represent additional data tied to the user. You can store property values in an array, but note that Amplitude only supports one-dimensional arrays. Date values are transformed into string values. Object depth may not exceed 40 layers.',
    default: {
      '@path': '$.traits'
    }
  },
  groups: {
    label: 'Groups',
    type: 'object',
    description:
      'Groups of users for the event as an event-level group. You can only track up to 5 groups. **Note:** This Amplitude feature is only available to Enterprise customers who have purchased the Accounts add-on.'
  },
  app_version: {
    label: 'App Version',
    type: 'string',
    description: 'The current version of your application.',
    default: {
      '@path': '$.context.app.version'
    }
  },
  platform: {
    label: 'Platform',
    type: 'string',
    description:
      'Platform of the device. If using analytics.js to send events from a Browser and no if no Platform value is provided, the value "Web" will be sent.',
    default: {
      '@path': '$.context.device.type'
    }
  },
  os_name: {
    label: 'OS Name',
    type: 'string',
    description: 'The name of the mobile operating system or browser that the user is using.',
    default: {
      '@path': '$.context.os.name'
    }
  },
  os_version: {
    label: 'OS Version',
    type: 'string',
    description: 'The version of the mobile operating system or browser the user is using.',
    default: {
      '@path': '$.context.os.version'
    }
  },
  device_brand: {
    label: 'Device Brand',
    type: 'string',
    description: 'The device brand that the user is using.',
    default: {
      '@path': '$.context.device.brand'
    }
  },
  device_manufacturer: {
    label: 'Device Manufacturer',
    type: 'string',
    description: 'The device manufacturer that the user is using.',
    default: {
      '@path': '$.context.device.manufacturer'
    }
  },
  device_model: {
    label: 'Device Model',
    type: 'string',
    description: 'The device model that the user is using.',
    default: {
      '@path': '$.context.device.model'
    }
  },
  carrier: {
    label: 'Carrier',
    type: 'string',
    description: 'The carrier that the user is using.',
    default: {
      '@path': '$.context.network.carrier'
    }
  },
  country: {
    label: 'Country',
    type: 'string',
    description: 'The current country of the user.',
    default: {
      '@path': '$.context.location.country'
    }
  },
  region: {
    label: 'Region',
    type: 'string',
    description: 'The current region of the user.',
    default: {
      '@path': '$.context.location.region'
    }
  },
  city: {
    label: 'City',
    type: 'string',
    description: 'The current city of the user.',
    default: {
      '@path': '$.context.location.city'
    }
  },
  dma: {
    label: 'Designated Market Area',
    type: 'string',
    description: 'The current Designated Market Area of the user.'
  },
  language: {
    label: 'Language',
    type: 'string',
    description: 'The language set by the user.',
    default: {
      '@path': '$.context.locale'
    }
  },
  price: {
    label: 'Price',
    type: 'number',
    description:
      'The price of the item purchased. Required for revenue data if the revenue field is not sent. You can use negative values to indicate refunds.',
    default: {
      '@path': '$.properties.price'
    }
  },
  quantity: {
    label: 'Quantity',
    type: 'integer',
    description: 'The quantity of the item purchased. Defaults to 1 if not specified.',
    default: {
      '@path': '$.properties.quantity'
    }
  },
  revenue: {
    label: 'Revenue',
    type: 'number',
    description:
      'Revenue = price * quantity. If you send all 3 fields of price, quantity, and revenue, then (price * quantity) will be used as the revenue value. You can use negative values to indicate refunds. **Note:** You will need to explicitly set this if you are using the Amplitude in cloud-mode.',
    default: {
      '@path': '$.properties.revenue'
    }
  },
  productId: {
    label: 'Product ID',
    type: 'string',
    description: 'An identifier for the item purchased. You must send a price and quantity or revenue with this field.',
    default: {
      '@path': '$.properties.productId'
    }
  },
  revenueType: {
    label: 'Revenue Type',
    type: 'string',
    description:
      'The type of revenue for the item purchased. You must send a price and quantity or revenue with this field.',
    default: {
      '@path': '$.properties.revenueType'
    }
  },
  location_lat: {
    label: 'Latitude',
    type: 'number',
    description: 'The current Latitude of the user.',
    default: {
      '@path': '$.context.location.latitude'
    }
  },
  location_lng: {
    label: 'Longtitude',
    type: 'number',
    description: 'The current Longitude of the user.',
    default: {
      '@path': '$.context.location.longitude'
    }
  },
  ip: {
    label: 'IP Address',
    type: 'string',
    description:
      'The IP address of the user. Use "$remote" to use the IP address on the upload request. Amplitude will use the IP address to reverse lookup a user\'s location (city, country, region, and DMA). Amplitude has the ability to drop the location and IP address from events once it reaches our servers. You can submit a request to Amplitude\'s platform specialist team here to configure this for you.',
    default: {
      '@path': '$.context.ip'
    }
  },
  idfa: {
    label: 'Identifier For Advertiser (IDFA)',
    type: 'string',
    description: 'Identifier for Advertiser. _(iOS)_',
    default: {
      '@if': {
        exists: { '@path': '$.context.device.advertisingId' },
        then: { '@path': '$.context.device.advertisingId' },
        else: { '@path': '$.context.device.idfa' }
      }
    }
  },
  idfv: {
    label: 'Identifier For Vendor (IDFV)',
    type: 'string',
    description: 'Identifier for Vendor. _(iOS)_',
    default: {
      '@path': '$.context.device.id'
    }
  },
  adid: {
    label: 'Google Play Services Advertising ID',
    type: 'string',
    description: 'Google Play Services advertising ID. _(Android)_',
    default: {
      '@if': {
        exists: { '@path': '$.context.device.advertisingId' },
        then: { '@path': '$.context.device.advertisingId' },
        else: { '@path': '$.context.device.idfa' }
      }
    }
  },
  android_id: {
    label: 'Android ID',
    type: 'string',
    description: 'Android ID (not the advertising ID). _(Android)_'
  },
  event_id: {
    label: 'Event ID',
    type: 'integer',
    description:
      'An incrementing counter to distinguish events with the same user ID and timestamp from each other. Amplitude recommends you send an event ID, increasing over time, especially if you expect events to occur simultanenously.'
  },
  insert_id: {
    label: 'Insert ID',
    type: 'string',
    description:
      'Amplitude will deduplicate subsequent events sent with this ID we have already seen before within the past 7 days. Amplitude recommends generating a UUID or using some combination of device ID, user ID, event type, event ID, and time.'
  },
  library: {
    label: 'Library',
    type: 'string',
    description: 'The name of the library that generated the event.',
    default: {
      '@path': '$.context.library.name'
    }
  }
}

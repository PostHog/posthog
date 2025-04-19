// Generated file. DO NOT MODIFY IT BY HAND.

export interface Payload {
  /**
   * A readable ID specified by you. Must have a minimum length of 5 characters. Required unless device ID is present. **Note:** If you send a request with a user ID that is not in the Amplitude system yet, then the user tied to that ID will not be marked new until their first event.
   */
  user_id?: string | null
  /**
   * A device-specific identifier, such as the Identifier for Vendor on iOS. Required unless user ID is present. If a device ID is not sent with the event, it will be set to a hashed version of the user ID.
   */
  device_id?: string
  /**
   * A unique identifier for your event.
   */
  event_type: string
  /**
   * The start time of the session, necessary if you want to associate events with a particular system. To use automatic Amplitude session tracking in browsers, enable Analytics 2.0 on your connected source.
   */
  session_id?: string | number
  /**
   * The timestamp of the event. If time is not sent with the event, it will be set to the request upload time.
   */
  time?: string | number
  /**
   * An object of key-value pairs that represent additional data to be sent along with the event. You can store property values in an array, but note that Amplitude only supports one-dimensional arrays. Date values are transformed into string values. Object depth may not exceed 40 layers.
   */
  event_properties?: {
    [k: string]: unknown
  }
  /**
   * An object of key-value pairs that represent additional data tied to the user. You can store property values in an array, but note that Amplitude only supports one-dimensional arrays. Date values are transformed into string values. Object depth may not exceed 40 layers.
   */
  user_properties?: {
    [k: string]: unknown
  }
  /**
   * Groups of users for the event as an event-level group. You can only track up to 5 groups. **Note:** This Amplitude feature is only available to Enterprise customers who have purchased the Accounts add-on.
   */
  groups?: {
    [k: string]: unknown
  }
  /**
   * The current version of your application.
   */
  app_version?: string
  /**
   * Platform of the device. If using analytics.js to send events from a Browser and no if no Platform value is provided, the value "Web" will be sent.
   */
  platform?: string
  /**
   * The name of the mobile operating system or browser that the user is using.
   */
  os_name?: string
  /**
   * The version of the mobile operating system or browser the user is using.
   */
  os_version?: string
  /**
   * The device brand that the user is using.
   */
  device_brand?: string
  /**
   * The device manufacturer that the user is using.
   */
  device_manufacturer?: string
  /**
   * The device model that the user is using.
   */
  device_model?: string
  /**
   * The carrier that the user is using.
   */
  carrier?: string
  /**
   * The current country of the user.
   */
  country?: string
  /**
   * The current region of the user.
   */
  region?: string
  /**
   * The current city of the user.
   */
  city?: string
  /**
   * The current Designated Market Area of the user.
   */
  dma?: string
  /**
   * The language set by the user.
   */
  language?: string
  /**
   * The price of the item purchased. Required for revenue data if the revenue field is not sent. You can use negative values to indicate refunds.
   */
  price?: number
  /**
   * The quantity of the item purchased. Defaults to 1 if not specified.
   */
  quantity?: number
  /**
   * Revenue = price * quantity. If you send all 3 fields of price, quantity, and revenue, then (price * quantity) will be used as the revenue value. You can use negative values to indicate refunds. **Note:** You will need to explicitly set this if you are using the Amplitude in cloud-mode.
   */
  revenue?: number
  /**
   * An identifier for the item purchased. You must send a price and quantity or revenue with this field.
   */
  productId?: string
  /**
   * The type of revenue for the item purchased. You must send a price and quantity or revenue with this field.
   */
  revenueType?: string
  /**
   * The current Latitude of the user.
   */
  location_lat?: number
  /**
   * The current Longitude of the user.
   */
  location_lng?: number
  /**
   * The IP address of the user. Use "$remote" to use the IP address on the upload request. Amplitude will use the IP address to reverse lookup a user's location (city, country, region, and DMA). Amplitude has the ability to drop the location and IP address from events once it reaches our servers. You can submit a request to Amplitude's platform specialist team here to configure this for you.
   */
  ip?: string
  /**
   * Identifier for Advertiser. _(iOS)_
   */
  idfa?: string
  /**
   * Identifier for Vendor. _(iOS)_
   */
  idfv?: string
  /**
   * Google Play Services advertising ID. _(Android)_
   */
  adid?: string
  /**
   * Android ID (not the advertising ID). _(Android)_
   */
  android_id?: string
  /**
   * An incrementing counter to distinguish events with the same user ID and timestamp from each other. Amplitude recommends you send an event ID, increasing over time, especially if you expect events to occur simultanenously.
   */
  event_id?: number
  /**
   * Amplitude will deduplicate subsequent events sent with this ID we have already seen before within the past 7 days. Amplitude recommends generating a UUID or using some combination of device ID, user ID, event type, event ID, and time.
   */
  insert_id?: string
  /**
   * The name of the library that generated the event.
   */
  library?: string
  /**
   * The list of products purchased.
   */
  products?: {
    /**
     * The price of the item purchased. Required for revenue data if the revenue field is not sent. You can use negative values to indicate refunds.
     */
    price?: number
    /**
     * The quantity of the item purchased. Defaults to 1 if not specified.
     */
    quantity?: number
    /**
     * Revenue = price * quantity. If you send all 3 fields of price, quantity, and revenue, then (price * quantity) will be used as the revenue value. You can use negative values to indicate refunds.
     */
    revenue?: number
    /**
     * An identifier for the item purchased. You must send a price and quantity or revenue with this field.
     */
    productId?: string
    /**
     * The type of revenue for the item purchased. You must send a price and quantity or revenue with this field.
     */
    revenueType?: string
    [k: string]: unknown
  }[]
  /**
   * The following fields will only be set as user properties if they do not already have a value.
   */
  setOnce?: {
    /**
     * The referrer of the web request.
     */
    initial_referrer?: string
    initial_utm_source?: string
    initial_utm_medium?: string
    initial_utm_campaign?: string
    initial_utm_term?: string
    initial_utm_content?: string
    [k: string]: unknown
  }
  /**
   * The following fields will be set as user properties for every event.
   */
  setAlways?: {
    referrer?: string
    utm_source?: string
    utm_medium?: string
    utm_campaign?: string
    utm_term?: string
    utm_content?: string
    [k: string]: unknown
  }
  /**
   * Increment a user property by a number with add. If the user property doesn't have a value set yet, it's initialized to 0.
   */
  add?: {
    [k: string]: unknown
  }
  /**
   * If true, events are sent to Amplitude's `batch` endpoint rather than their `httpapi` events endpoint. Enabling this setting may help reduce 429s – or throttling errors – from Amplitude. More information about Amplitude's throttling is available in [their docs](https://developers.amplitude.com/docs/batch-event-upload-api#429s-in-depth).
   */
  use_batch_endpoint?: boolean
  /**
   * The user agent of the device sending the event.
   */
  userAgent?: string
  /**
   * Enabling this setting will set the Device manufacturer, Device Model and OS Name properties based on the user agent string provided in the userAgent field.
   */
  userAgentParsing?: boolean
  /**
   * Enabling this setting will send user_agent based on the raw user agent string provided in the userAgent field
   */
  includeRawUserAgent?: boolean
  /**
   * Amplitude has a default minimum id length of 5 characters for user_id and device_id fields. This field allows the minimum to be overridden to allow shorter id lengths.
   */
  min_id_length?: number | null
  /**
   * The user agent data of device sending the event
   */
  userAgentData?: {
    model?: string
    platformVersion?: string
  }
}

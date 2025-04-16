// Generated file. DO NOT MODIFY IT BY HAND.

export interface Payload {
  /**
   * A UUID (unique user ID) specified by you. **Note:** If you send a request with a user ID that is not in the Amplitude system yet, then the user tied to that ID will not be marked new until their first event. Required unless device ID is present.
   */
  user_id?: string | null
  /**
   * A device specific identifier, such as the Identifier for Vendor (IDFV) on iOS. Required unless user ID is present.
   */
  device_id?: string
  /**
   * Additional data tied to the user in Amplitude. Each distinct value will show up as a user segment on the Amplitude dashboard. Object depth may not exceed 40 layers. **Note:** You can store property values in an array and date values are transformed into string values.
   */
  user_properties?: {
    [k: string]: unknown
  }
  /**
   * Groups of users for Amplitude's account-level reporting feature. Note: You can only track up to 5 groups. Any groups past that threshold will not be tracked. **Note:** This feature is only available to Amplitude Enterprise customers who have purchased the Amplitude Accounts add-on.
   */
  groups?: {
    [k: string]: unknown
  }
  /**
   * Version of the app the user is on.
   */
  app_version?: string
  /**
   * The platform of the user's device.
   */
  platform?: string
  /**
   * The mobile operating system or browser of the user's device.
   */
  os_name?: string
  /**
   * The version of the mobile operating system or browser of the user's device.
   */
  os_version?: string
  /**
   * The brand of user's the device.
   */
  device_brand?: string
  /**
   * The manufacturer of the user's device.
   */
  device_manufacturer?: string
  /**
   * The model of the user's device.
   */
  device_model?: string
  /**
   * The user's mobile carrier.
   */
  carrier?: string
  /**
   * The country in which the user is located.
   */
  country?: string
  /**
   * The geographical region in which the user is located.
   */
  region?: string
  /**
   * The city in which the user is located.
   */
  city?: string
  /**
   * The Designated Market Area in which the user is located.
   */
  dma?: string
  /**
   * Language the user has set on their device or browser.
   */
  language?: string
  /**
   * Whether the user is paying or not.
   */
  paying?: boolean
  /**
   * The version of the app the user was first on.
   */
  start_version?: string
  /**
   * Amplitude will deduplicate subsequent events sent with this ID we have already seen before within the past 7 days. Amplitude recommends generating a UUID or using some combination of device ID, user ID, event type, event ID, and time.
   */
  insert_id?: string
  /**
   * The user agent of the device sending the event.
   */
  userAgent?: string
  /**
   * Enabling this setting will set the Device manufacturer, Device Model and OS Name properties based on the user agent string provided in the userAgent field
   */
  userAgentParsing?: boolean
  /**
   * Enabling this setting will send user_agent based on the raw user agent string provided in the userAgent field
   */
  includeRawUserAgent?: boolean
  /**
   * UTM Tracking Properties
   */
  utm_properties?: {
    utm_source?: string
    utm_medium?: string
    utm_campaign?: string
    utm_term?: string
    utm_content?: string
  }
  /**
   * The referrer of the web request. Sent to Amplitude as both last touch “referrer” and first touch “initial_referrer”
   */
  referrer?: string
  /**
   * Amplitude has a default minimum id length of 5 characters for user_id and device_id fields. This field allows the minimum to be overridden to allow shorter id lengths.
   */
  min_id_length?: number | null
  /**
   * The name of the library that generated the event.
   */
  library?: string
  /**
   * The user agent data of device sending the event
   */
  userAgentData?: {
    model?: string
    platformVersion?: string
  }
}

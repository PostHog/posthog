// Generated file. DO NOT MODIFY IT BY HAND.

export interface Payload {
  /**
   * The User ID to be associated.
   */
  user_id?: string
  /**
   * The Global User ID to associate with the User ID.
   */
  global_user_id?: string
  /**
   * Amplitude has a default minimum id length (`min_id_length`) of 5 characters for user_id and device_id fields. This field allows the minimum to be overridden to allow shorter id lengths.
   */
  min_id_length?: number | null
}

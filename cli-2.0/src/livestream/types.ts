export type LivestreamCredentials = {
  host: string // e.g., https://us.posthog.com
  livestreamHost: string // e.g., https://live.us.posthog.com
  token: string // JWT with aud: "posthog:livestream"
  teamId: number
  teamName: string
  expiresAt: number // Unix timestamp
}

export type EventMsg = {
  uuid: string
  timestamp: string | number
  distinct_id: string
  person_id: string
  event: string
  properties: Record<string, unknown>
}

export type GeoEventMsg = {
  lat: number
  lng: number
  country_code: string
  distinct_id: string
  count: number
}

export type LivestreamOptions = {
  token?: string
  host?: string
  livestreamHost?: string
  eventType?: string
  distinctId?: string
  geo?: boolean
}

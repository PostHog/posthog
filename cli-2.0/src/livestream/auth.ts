import { config } from '../config.js'
import type { LivestreamCredentials } from './types.js'
import { deriveLivestreamHost } from './utils/host.js'
import { secureStorage } from './utils/keychain.js'

type AuthOptions = { token?: string; host?: string; livestreamHost?: string }

const loadCredentials = (): LivestreamCredentials | null => {
  try {
    const data = secureStorage.get()
    if (!data) return null
    return JSON.parse(data)
  } catch {
    return null
  }
}

const saveCredentials = (creds: LivestreamCredentials): void => {
  secureStorage.set(JSON.stringify(creds))
}

// Fetches the livestream JWT from the PostHog API using an OAuth access token
const fetchLivestreamToken = async (
  accessToken: string,
  host: string,
  projectId: string
): Promise<{ token: string; teamId: number; teamName: string } | null> => {
  try {
    const url = new URL(`/api/projects/${projectId}/`, host)
    const response = await fetch(url.toString(), {
      headers: {
        Authorization: `Bearer ${accessToken}`,
        'Content-Type': 'application/json',
        'User-Agent': 'PostHog-CLI-2.0/0.1.0',
      },
    })

    if (!response.ok) {
      return null
    }

    const data = (await response.json()) as {
      id: number
      name?: string
      live_events_token?: string
    }

    if (!data.live_events_token) {
      return null
    }

    return {
      token: data.live_events_token,
      teamId: data.id,
      teamName: data.name || '',
    }
  } catch {
    return null
  }
}

export const authenticate = async (opts: AuthOptions): Promise<LivestreamCredentials> => {
  // Priority 1: direct token flag (for scripting)
  if (opts.token) {
    const host = opts.host || 'https://app.posthog.com'
    const livestreamHost = opts.livestreamHost || deriveLivestreamHost(host)
    return {
      host,
      livestreamHost,
      token: opts.token,
      teamId: 0,
      teamName: '',
      expiresAt: Date.now() + 7 * 24 * 60 * 60 * 1000,
    }
  }

  // OAuth is the source of truth - ensure we have a valid OAuth token
  const mainConfig = await config.ensureAuth()

  if (!mainConfig.accessToken || !mainConfig.projectId || !mainConfig.host) {
    throw new Error('Authentication failed. Run: ph auth login')
  }

  // Check if we have a valid cached JWT for this project
  const cached = loadCredentials()
  if (cached && cached.expiresAt > Date.now() && cached.teamId === Number(mainConfig.projectId)) {
    return cached
  }

  // Silently fetch a new JWT using the OAuth token
  const result = await fetchLivestreamToken(
    mainConfig.accessToken,
    mainConfig.host,
    mainConfig.projectId
  )

  if (!result) {
    throw new Error('Failed to obtain livestream token. Please try again.')
  }

  const livestreamHost = opts.livestreamHost || deriveLivestreamHost(mainConfig.host)
  const creds: LivestreamCredentials = {
    host: mainConfig.host,
    livestreamHost,
    token: result.token,
    teamId: result.teamId,
    teamName: result.teamName,
    expiresAt: Date.now() + 7 * 24 * 60 * 60 * 1000, // JWT valid for 7 days
  }

  saveCredentials(creds)

  return creds
}

export const clearCredentials = (): void => {
  secureStorage.delete()
}

import { createServer } from 'node:http'
import open from 'open'
import type { LivestreamCredentials } from './types.js'
import { deriveLivestreamHost } from './utils/host.js'
import { secureStorage } from './utils/keychain.js'

type AuthOptions = { token?: string; host?: string }

type CallbackResult = {
  token: string
  teamName: string
  teamId: number
  apiHost: string
}

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

const startCallbackServer = (): Promise<{ port: number; waitForCallback: () => Promise<CallbackResult> }> => {
  return new Promise((resolve, reject) => {
    let callbackResolve: (result: CallbackResult) => void

    const server = createServer((req, res) => {
      const url = new URL(req.url!, `http://localhost`)
      if (url.pathname === '/callback') {
        const token = url.searchParams.get('token')
        const teamName = url.searchParams.get('team_name') || ''
        const teamId = parseInt(url.searchParams.get('team_id') || '0', 10)
        const apiHost = url.searchParams.get('api_host') || ''

        res.writeHead(200, { 'Content-Type': 'text/html' })
        res.end(`<html><body style="font-family:system-ui;display:flex;justify-content:center;align-items:center;height:100vh;background:#1d1f27;color:#fff">
          <div style="text-align:center"><h1 style="color:#F54E00">Authorization complete!</h1><p>You can close this tab.</p></div>
        </body></html>`)

        server.close()
        callbackResolve({ token: token || '', teamName, teamId, apiHost })
      }
    })

    server.listen(0, '127.0.0.1', () => {
      const addr = server.address()
      const port = typeof addr === 'object' ? addr!.port : 0
      resolve({
        port,
        waitForCallback: () => new Promise((r) => { callbackResolve = r }),
      })
    })

    server.on('error', reject)
  })
}

export const authenticate = async (opts: AuthOptions): Promise<LivestreamCredentials> => {
  const host = opts.host || 'https://app.posthog.com'

  // Priority 1: direct token flag
  if (opts.token) {
    return {
      host,
      livestreamHost: deriveLivestreamHost(host),
      token: opts.token,
      teamId: 0,
      teamName: '',
      expiresAt: Date.now() + 7 * 24 * 60 * 60 * 1000,
    }
  }

  // Priority 2: cached credentials (if not expired)
  const cached = loadCredentials()
  if (cached && cached.expiresAt > Date.now()) {
    return cached
  }

  // Priority 3: browser flow
  const { port, waitForCallback } = await startCallbackServer()
  const url = `${host}/cli/live?port=${port}`

  console.error(`Opening browser to authorize: ${url}`)
  await open(url)
  console.error('Waiting for authorization...')

  const result = await waitForCallback()

  const creds: LivestreamCredentials = {
    host: result.apiHost || host,
    livestreamHost: deriveLivestreamHost(result.apiHost || host),
    token: result.token,
    teamId: result.teamId,
    teamName: result.teamName,
    expiresAt: Date.now() + 7 * 24 * 60 * 60 * 1000,
  }

  saveCredentials(creds)

  if (secureStorage.isSecure) {
    console.error('Credentials stored securely in macOS Keychain')
  }

  return creds
}

export const clearCredentials = (): void => {
  secureStorage.delete()
}

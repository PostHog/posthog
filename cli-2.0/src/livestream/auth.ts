import { createServer, type Server } from 'node:http'
import open from 'open'
import type { LivestreamCredentials } from './types.js'
import { deriveLivestreamHost } from './utils/host.js'
import { secureStorage } from './utils/keychain.js'

type AuthOptions = { token?: string; host?: string; livestreamHost?: string }

type CallbackResult = {
  token: string
  teamName: string
  teamId: number
  apiHost: string
}

const AUTH_TIMEOUT_MS = 5 * 60 * 1000 // 5 minutes

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

type CallbackServer = {
  port: number
  waitForCallback: Promise<CallbackResult>
  close: () => void
}

const startCallbackServer = (): Promise<CallbackServer> => {
  return new Promise((resolve, reject) => {
    // Create the result promise upfront to avoid race condition
    let callbackResolve: (result: CallbackResult) => void
    let callbackReject: (error: Error) => void
    const callbackPromise = new Promise<CallbackResult>((res, rej) => {
      callbackResolve = res
      callbackReject = rej
    })

    let server: Server
    let timeoutId: NodeJS.Timeout

    const cleanup = () => {
      clearTimeout(timeoutId)
      server?.close()
    }

    server = createServer((req, res) => {
      const url = new URL(req.url!, `http://localhost`)
      if (url.pathname === '/callback') {
        const token = url.searchParams.get('token')
        const teamName = url.searchParams.get('team_name') || ''
        const teamId = parseInt(url.searchParams.get('team_id') || '0', 10)
        const apiHost = url.searchParams.get('api_host') || ''

        if (!token) {
          res.writeHead(400, { 'Content-Type': 'text/html' })
          res.end(`<html><body style="font-family:system-ui;display:flex;justify-content:center;align-items:center;height:100vh;background:#1d1f27;color:#fff">
            <div style="text-align:center"><h1 style="color:#F54E00">Authorization failed</h1><p>No token received. Please try again.</p></div>
          </body></html>`)
          cleanup()
          callbackReject(new Error('No token received from callback'))
          return
        }

        res.writeHead(200, { 'Content-Type': 'text/html' })
        res.end(`<html><body style="font-family:system-ui;display:flex;justify-content:center;align-items:center;height:100vh;background:#1d1f27;color:#fff">
          <div style="text-align:center"><h1 style="color:#F54E00">Authorization complete!</h1><p>You can close this tab.</p></div>
        </body></html>`)

        cleanup()
        callbackResolve({ token, teamName, teamId, apiHost })
      }
    })

    server.listen(0, '127.0.0.1', () => {
      const addr = server.address()
      const port = typeof addr === 'object' ? addr!.port : 0

      // Set up timeout
      timeoutId = setTimeout(() => {
        cleanup()
        callbackReject(new Error('Authorization timed out after 5 minutes'))
      }, AUTH_TIMEOUT_MS)

      resolve({
        port,
        waitForCallback: callbackPromise,
        close: cleanup,
      })
    })

    server.on('error', (err) => {
      cleanup()
      reject(err)
    })
  })
}

export const authenticate = async (opts: AuthOptions): Promise<LivestreamCredentials> => {
  const host = opts.host || 'https://app.posthog.com'

  // Priority 1: direct token flag
  if (opts.token) {
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

  // Priority 2: cached credentials (if not expired)
  const cached = loadCredentials()
  if (cached && cached.expiresAt > Date.now()) {
    return cached
  }

  // Priority 3: browser flow
  const callbackServer = await startCallbackServer()
  const url = `${host}/cli/live?port=${callbackServer.port}`

  console.error(`Opening browser to authorize: ${url}`)

  try {
    await open(url)
  } catch {
    console.error(`Could not open browser automatically.`)
    console.error(`Please open this URL manually: ${url}`)
  }

  console.error('Waiting for authorization (timeout: 5 minutes)...')

  let result: CallbackResult
  try {
    result = await callbackServer.waitForCallback
  } catch (err) {
    callbackServer.close()
    throw err
  }

  const livestreamHost = opts.livestreamHost || deriveLivestreamHost(result.apiHost || host)

  const creds: LivestreamCredentials = {
    host: result.apiHost || host,
    livestreamHost,
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

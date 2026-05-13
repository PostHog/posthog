import crypto from 'node:crypto'
import http from 'node:http'
import { spawn } from 'node:child_process'

export interface OAuthMetadata {
  authorization_endpoint: string
  token_endpoint: string
  registration_endpoint: string
}

export interface OAuthClientRegistration {
  client_id: string
  client_secret?: string
}

export interface OAuthTokenResponse {
  access_token: string
  refresh_token?: string
  expires_in?: number
  token_type?: string
  scope?: string
  scoped_teams?: number[]
  scoped_organizations?: string[]
  posthog_region?: string
  posthog_base_url?: string
}

interface CallbackServer {
  redirectUri: string
  waitForCallback: Promise<string>
  close: () => Promise<void>
}

const OAUTH_ISSUER = 'https://oauth.posthog.com'

export const DEFAULT_OAUTH_SCOPES = [
  'openid',
    'profile',
    'email',
    'action:read',
    'action:write',
    'access_control:read',
    'access_control:write',
    'activity_log:read',
    'activity_log:write',
    'alert:read',
    'alert:write',
    'annotation:read',
    'annotation:write',
    'approvals:read',
    'approvals:write',
    'batch_export:read',
    'batch_export:write',
    'batch_import:read',
    'batch_import:write',
    'business_knowledge:read',
    'business_knowledge:write',
    'cohort:read',
    'cohort:write',
    'comment:read',
    'comment:write',
    'conversation:read',
    'conversation:write',
    'customer_analytics:read',
    'customer_analytics:write',
    'customer_journey:read',
    'customer_journey:write',
    'customer_profile_config:read',
    'customer_profile_config:write',
    'dashboard:read',
    'dashboard:write',
    'event_filter:read',
    'event_filter:write',
    'dashboard_template:read',
    'dashboard_template:write',
    'dataset:read',
    'dataset:write',
    'desktop_recording:read',
    'desktop_recording:write',
    'early_access_feature:read',
    'early_access_feature:write',
    'endpoint:read',
    'endpoint:write',
    'error_tracking:read',
    'error_tracking:write',
    'evaluation:read',
    'evaluation:write',
    'element:read',
    'element:write',
    'event_definition:read',
    'event_definition:write',
    'experiment:read',
    'experiment:write',
    'experiment_saved_metric:read',
    'experiment_saved_metric:write',
    'export:read',
    'export:write',
    'external_data_schema:read',
    'external_data_schema:write',
    'external_data_source:read',
    'external_data_source:write',
    'feature_flag:read',
    'feature_flag:write',
    'file_system:read',
    'file_system:write',
    'file_system_shortcut:read',
    'file_system_shortcut:write',
    'group:read',
    'group:write',
    'health_issue:read',
    'health_issue:write',
    'heatmap:read',
    'heatmap:write',
    'hog_flow:read',
    'hog_flow:write',
    'hog_function:read',
    'hog_function:write',
    'insight:read',
    'insight:write',
    'insight_variable:read',
    'insight_variable:write',
    'integration:read',
    'integration:write',
    'legal_document:read',
    'legal_document:write',
    'link:read',
    'link:write',
    'live_debugger:read',
    'live_debugger:write',
    'llm_analytics:read',
    'llm_analytics:write',
    'llm_gateway:read',
    'llm_gateway:write',
    'llm_prompt:read',
    'llm_prompt:write',
    'llm_provider_key:read',
    'llm_provider_key:write',
    'llm_skill:read',
    'llm_skill:write',
    'logs:read',
    'logs:write',
    'notebook:read',
    'notebook:write',
    'organization:read',
    'organization:write',
    'organization_integration:read',
    'organization_integration:write',
    'organization_member:read',
    'organization_member:write',
    'person:read',
    'person:write',
    'persisted_folder:read',
    'persisted_folder:write',
    'plugin:read',
    'plugin:write',
    'product_tour:read',
    'product_tour:write',
    'project:read',
    'project:write',
    'property_definition:read',
    'property_definition:write',
    'query:read',
    'query:write',
    'revenue_analytics:read',
    'revenue_analytics:write',
    'session_recording:read',
    'session_recording:write',
    'session_recording_playlist:read',
    'session_recording_playlist:write',
    'sharing_configuration:read',
    'sharing_configuration:write',
    'streamlit_app:read',
    'streamlit_app:write',
    'subscription:read',
    'subscription:write',
    'survey:read',
    'survey:write',
    'tagger:read',
    'tagger:write',
    'ticket:read',
    'ticket:write',
    'task:read',
    'task:write',
    'tracing:read',
    'tracing:write',
    'uploaded_media:read',
    'uploaded_media:write',
    'usage_metric:read',
    'usage_metric:write',
    'user:read',
    'user:write',
    'visual_review:read',
    'visual_review:write',
    'warehouse_objects:read',
    'warehouse_objects:write',
    'warehouse_table:read',
    'warehouse_table:write',
    'warehouse_view:read',
    'warehouse_view:write',
    'web_analytics:read',
    'web_analytics:write',
    'webhook:read',
    'webhook:write',
]

export function getOAuthScopes(): string[] {
  return (process.env.POSTHOG_CLI_OAUTH_SCOPES || DEFAULT_OAUTH_SCOPES.join(' '))
    .split(/\s+/)
    .map((scope) => scope.trim())
    .filter(Boolean)
}

export async function fetchOAuthMetadata(): Promise<OAuthMetadata> {
  return requestJson<OAuthMetadata>(`${OAUTH_ISSUER}/.well-known/oauth-authorization-server`)
}

export async function registerOAuthClient(
  metadata: OAuthMetadata,
  redirectUri: string
): Promise<OAuthClientRegistration> {
  return requestJson<OAuthClientRegistration>(metadata.registration_endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      client_name: 'PH CLI',
      redirect_uris: [redirectUri],
      grant_types: ['authorization_code', 'refresh_token'],
      response_types: ['code'],
      token_endpoint_auth_method: 'none',
    }),
  })
}

export function generatePkce(): { codeVerifier: string; codeChallenge: string } {
  const codeVerifier = crypto.randomBytes(32).toString('base64url')
  const codeChallenge = crypto.createHash('sha256').update(codeVerifier).digest('base64url')
  return { codeVerifier, codeChallenge }
}

export async function startCallbackServer(expectedState: string): Promise<CallbackServer> {
  let server: http.Server | undefined

  const waitForCallback = new Promise<string>((resolve, reject) => {
    server = http.createServer((req, res) => {
      const requestUrl = new URL(req.url || '/', 'http://127.0.0.1')

      if (requestUrl.pathname !== '/oauth/callback') {
        res.writeHead(404, { 'Content-Type': 'text/plain' })
        res.end('Not found')
        return
      }

      const error = requestUrl.searchParams.get('error')
      if (error) {
        res.writeHead(400, { 'Content-Type': 'text/html; charset=utf-8' })
        res.end('<h1>PostHog login failed</h1><p>You can close this window and return to the CLI.</p>')
        reject(new Error(`${error}: ${requestUrl.searchParams.get('error_description') || 'OAuth authorization failed'}`))
        return
      }

      const state = requestUrl.searchParams.get('state')
      if (state !== expectedState) {
        res.writeHead(400, { 'Content-Type': 'text/html; charset=utf-8' })
        res.end('<h1>PostHog login failed</h1><p>Invalid OAuth state. You can close this window.</p>')
        reject(new Error('Invalid OAuth state returned by authorization server'))
        return
      }

      const code = requestUrl.searchParams.get('code')
      if (!code) {
        res.writeHead(400, { 'Content-Type': 'text/html; charset=utf-8' })
        res.end('<h1>PostHog login failed</h1><p>Missing authorization code. You can close this window.</p>')
        reject(new Error('Missing authorization code'))
        return
      }

      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' })
      res.end('<h1>PostHog login complete</h1><p>You can close this window and return to the CLI.</p>')
      resolve(code)
    })

    server.on('error', reject)
  })

  await new Promise<void>((resolve, reject) => {
    if (!server) {
      reject(new Error('Failed to create OAuth callback server'))
      return
    }

    server.listen(0, '127.0.0.1', () => resolve())
  })

  if (!server) {
    throw new Error('Failed to create OAuth callback server')
  }

  const oauthServer = server
  const address = oauthServer.address()
  if (!address || typeof address === 'string') {
    await closeServer(oauthServer)
    throw new Error('Failed to determine OAuth callback server port')
  }

  return {
    redirectUri: `http://127.0.0.1:${address.port}/oauth/callback`,
    waitForCallback,
    close: () => closeServer(oauthServer),
  }
}

export function buildAuthorizeUrl(params: {
  metadata: OAuthMetadata
  clientId: string
  redirectUri: string
  state: string
  codeChallenge: string
  scopes: string[]
}): string {
  const authorizeUrl = new URL(params.metadata.authorization_endpoint)
  authorizeUrl.searchParams.set('client_id', params.clientId)
  authorizeUrl.searchParams.set('redirect_uri', params.redirectUri)
  authorizeUrl.searchParams.set('response_type', 'code')
  authorizeUrl.searchParams.set('scope', params.scopes.join(' '))
  authorizeUrl.searchParams.set('state', params.state)
  authorizeUrl.searchParams.set('code_challenge', params.codeChallenge)
  authorizeUrl.searchParams.set('code_challenge_method', 'S256')
  return authorizeUrl.toString()
}

export function openBrowser(url: string): void {
  const command = process.platform === 'darwin' ? 'open' : process.platform === 'win32' ? 'cmd' : 'xdg-open'
  const args = process.platform === 'win32' ? ['/c', 'start', '', url] : [url]

  const child = spawn(command, args, { detached: true, stdio: 'ignore' })
  child.on('error', () => {
    // The URL is also printed by the caller, so failing to open a browser is non-fatal.
  })
  child.unref()
}

export async function exchangeAuthorizationCode(params: {
  metadata: OAuthMetadata
  clientId: string
  code: string
  redirectUri: string
  codeVerifier: string
}): Promise<OAuthTokenResponse> {
  return requestJson<OAuthTokenResponse>(params.metadata.token_endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      grant_type: 'authorization_code',
      code: params.code,
      client_id: params.clientId,
      redirect_uri: params.redirectUri,
      code_verifier: params.codeVerifier,
    }),
  })
}

export async function refreshOAuthToken(params: {
  clientId: string
  refreshToken: string
}): Promise<OAuthTokenResponse> {
  const metadata = await fetchOAuthMetadata()
  return requestJson<OAuthTokenResponse>(metadata.token_endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      grant_type: 'refresh_token',
      refresh_token: params.refreshToken,
      client_id: params.clientId,
    }),
  })
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  const text = await response.text()
  let data: unknown

  try {
    data = text ? JSON.parse(text) : {}
  } catch {
    data = text
  }

  if (!response.ok) {
    const description =
      typeof data === 'object' && data !== null && 'error_description' in data
        ? String((data as { error_description: unknown }).error_description)
        : text
    throw new Error(`OAuth request failed: ${response.status} ${response.statusText}${description ? ` - ${description}` : ''}`)
  }

  return data as T
}

async function closeServer(server: http.Server): Promise<void> {
  if (!server.listening) {
    return
  }

  await new Promise<void>((resolve, reject) => {
    server.close((error) => {
      if (error) {
        reject(error)
        return
      }
      resolve()
    })
  })
}

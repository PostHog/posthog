import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { ApiClient } from './api-client.js'

function makeClient(): ApiClient {
  return new ApiClient({ apiToken: 'test-token', baseUrl: 'https://us.posthog.com' })
}

describe('ApiClient.request URL safety', () => {
  it('rejects protocol-relative paths that would leak the Authorization header', async () => {
    const client = makeClient()
    await assert.rejects(
      () => client.request({ method: 'GET', path: '//attacker.com/capture' }),
      /must be relative/,
    )
  })

  it('rejects absolute http URLs', async () => {
    const client = makeClient()
    await assert.rejects(
      () => client.request({ method: 'GET', path: 'http://attacker.com/capture' }),
      /must be relative/,
    )
  })

  it('rejects absolute https URLs regardless of case', async () => {
    const client = makeClient()
    await assert.rejects(
      () => client.request({ method: 'GET', path: 'HTTPS://attacker.com/capture' }),
      /must be relative/,
    )
  })
})

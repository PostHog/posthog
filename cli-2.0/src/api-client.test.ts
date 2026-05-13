import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { ApiClient } from './api-client.js'

function makeClient(): ApiClient {
  return new ApiClient({ apiToken: 'test-token', baseUrl: 'https://us.posthog.com' })
}

const rejectCases = [
  { name: 'protocol-relative paths that would leak the Authorization header', path: '//attacker.com/capture' },
  { name: 'absolute http URLs', path: 'http://attacker.com/capture' },
  { name: 'absolute https URLs regardless of case', path: 'HTTPS://attacker.com/capture' },
]

describe('ApiClient.request URL safety', () => {
  for (const { name, path } of rejectCases) {
    it(`rejects ${name}`, async () => {
      const client = makeClient()
      await assert.rejects(
        () => client.request({ method: 'GET', path }),
        /must be relative/,
      )
    })
  }
})

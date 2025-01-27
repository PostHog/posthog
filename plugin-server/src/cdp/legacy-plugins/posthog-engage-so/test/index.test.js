const { getMeta, resetMeta } = require('@posthog/plugin-scaffold/test/utils')
const { composeWebhook } = require('../index')
const config = {
  publicKey: 'ENGAGE_PUBLIC_KEY',
  secret: 'ENGAGE_SEECRET',
  filter: 'Send events for all users'
}

beforeEach(() => {
  resetMeta({
    config
  })
})

test('composeWebhook to send the correct data for $identify event (user)', async () => {
  const auth = 'Basic ' + Buffer.from(`${config.publicKey}:${config.secret}`).toString('base64')

  const event = {
    event: '$identify',
    distinct_id: 'user01',
    properties: {
      $set: {
        first_name: 'User',
        plan: 'Pro'
      },
      $set_once: {
        last_name: '01'
      },
      token: '[some token]',
      distinct_id: '[distinct_id]'
    }
  }

  const response = await composeWebhook(event, getMeta())
  expect(response).toEqual(
    expect.objectContaining({
      url: 'https://api.engage.so/posthog',
      body: JSON.stringify(event),
      headers: {
        'Content-Type': 'application/json',
        Authorization: auth
      },
      method: 'POST'
    })
  )
})

test('composeWebhook to send the correct data for $identify event (group)', async () => {
  const auth = 'Basic ' + Buffer.from(`${config.publicKey}:${config.secret}`).toString('base64')

  const event = {
    event: '$groupidentify',
    distinct_id: 'user01',
    properties: {
      $group_type: 'company',
      $group_key: 'group123',
      $group_set: {
        name: 'Group'
      }
    }
  }

  const response = await composeWebhook(event, getMeta())
  expect(response).toEqual(
    expect.objectContaining({
      url: 'https://api.engage.so/posthog',
      body: JSON.stringify(event),
      headers: {
        'Content-Type': 'application/json',
        Authorization: auth
      },
      method: 'POST'
    })
  )
})

test('composeWebhook to send the correct data to track user event', async () => {
  const auth = 'Basic ' + Buffer.from(`${config.publicKey}:${config.secret}`).toString('base64')

  const event = {
    event: 'newEvent',
    distinct_id: 'user01',
    properties: {
      $set: {
        number: '08012345678',
        currency: 'NG'
      },
      prop1: 'val1',
      prop2: 'val2'
    }
  }

  const response = await composeWebhook(event, getMeta())
  expect(response).toEqual(
    expect.objectContaining({
      url: 'https://api.engage.so/posthog',
      body: JSON.stringify(event),
      headers: {
        'Content-Type': 'application/json',
        Authorization: auth
      },
      method: 'POST'
    })
  )
})

test('composeWebhook to send the correct data to track group event', async () => {
  const auth = 'Basic ' + Buffer.from(`${config.publicKey}:${config.secret}`).toString('base64')

  const event = {
    event: 'Played movie',
    distinct_id: 'user01',
    properties: {
      $groups: {
        company: 'group123'
      },
      prop1: 'val1',
      prop2: 'val2'
    }
  }

  const response = await composeWebhook(event, getMeta())
  expect(response).toEqual(
    expect.objectContaining({
      url: 'https://api.engage.so/posthog',
      body: JSON.stringify(event),
      headers: {
        'Content-Type': 'application/json',
        Authorization: auth
      },
      method: 'POST'
    })
  )
})

test('composeWebhook should not track non-custom events besides $identify and $groupidentify', async () => {
  const auth = 'Basic ' + Buffer.from(`${config.publicKey}:${config.secret}`).toString('base64')

  const event = {
    event: '$pageview',
    properties: {
      $os: 'Mac OS X',
      $lib: 'web',
      $host: 'localhost:8000',
      $time: 1606383312.494,
      token: 'mre13a_SMBv9EwHAtdtTyutyy6AfO00OTPwaalaHPGgKLS',
      $browser: 'Chrome',
      $user_id: '3erf45reXthrGser675waeHFAsbv4AsadfR',
      $pathname: '/instance/status',
      $device_id: '17554768afe5cb-0fc915d2a583cf-166f6152-1ea000-175543686ffdc5',
      $insert_id: 'hgu2p36uvlc1b9dg',
      distinct_id: 'scbbAqF7uyrMmamV4QBzcA1rrm9wHNISdFweZz-mQ0',
      $current_url: 'http://localhost:8000/instance/status',
      $lib_version: '1.7.0-beta.1',
      $screen_width: 1790,
      $screen_height: 1120,
      posthog_version: '1.17.0',
      $browser_version: 86,
      $initial_referrer: '$direct',
      has_slack_webhook: false,
      $active_feature_flags: ['navigation-1775', 'session-recording-player'],
      $initial_referring_domain: '$direct'
    }
  }

  const response = await composeWebhook(event, getMeta())
  expect(response).toBe(null)
})

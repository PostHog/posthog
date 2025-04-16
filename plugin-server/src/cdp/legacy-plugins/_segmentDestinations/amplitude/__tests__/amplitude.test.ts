import nock from 'nock'
import { createTestEvent, createTestIntegration } from '@segment/actions-core'
import Amplitude from '../index'
import { DecoratedResponse } from '@segment/actions-core'

const testDestination = createTestIntegration(Amplitude)
const timestamp = '2021-08-17T15:21:15.449Z'

describe('Amplitude', () => {
  describe('logPurchase', () => {
    it('should work with default mappings', async () => {
      const event = createTestEvent({ timestamp, event: 'Test Event' })

      nock('https://api2.amplitude.com/2').post('/httpapi').reply(200, {})

      const responses = await testDestination.testAction('logPurchase', { event, useDefaultMappings: true })
      expect(responses.length).toBe(1)
      expect(responses[0].status).toBe(200)
      expect(responses[0].data).toMatchObject({})
      expect(responses[0].options.json).toMatchObject({
        api_key: undefined,
        events: expect.arrayContaining([
          expect.objectContaining({
            event_type: 'Test Event',
            city: 'San Francisco',
            country: 'United States'
          })
        ])
      })
    })

    it('should change casing for device type when value is ios', async () => {
      const event = createTestEvent({
        event: 'Test Event',
        context: {
          device: {
            id: 'foo',
            type: 'ios'
          }
        }
      })

      nock('https://api2.amplitude.com/2').post('/httpapi').reply(200, {})

      const responses = await testDestination.testAction('logPurchase', { event, useDefaultMappings: true })
      expect(responses[0].options.json).toMatchObject({
        api_key: undefined,
        events: expect.arrayContaining([
          expect.objectContaining({
            device_id: 'foo',
            platform: 'iOS'
          })
        ])
      })
    })

    it('should change casing for device type when value is android', async () => {
      const event = createTestEvent({
        event: 'Test Event',
        context: {
          device: {
            id: 'foo',
            type: 'android'
          }
        }
      })

      nock('https://api2.amplitude.com/2').post('/httpapi').reply(200, {})

      const responses = await testDestination.testAction('logPurchase', { event, useDefaultMappings: true })
      expect(responses[0].options.json).toMatchObject({
        api_key: undefined,
        events: expect.arrayContaining([
          expect.objectContaining({
            device_id: 'foo',
            platform: 'Android'
          })
        ])
      })
    })

    it('should set Platform field to "Web" when Library field = "analytics.js" and Platform field = null or undefined', async () => {
      const event = createTestEvent({
        event: 'Test Event',
        context: {
          device: {
            id: 'foo',
            type: null
          },
          library: {
            name: 'analytics.js',
            version: '2.11.1'
          }
        }
      })

      nock('https://api2.amplitude.com/2').post('/httpapi').reply(200, {})

      const responses = await testDestination.testAction('logPurchase', { event, useDefaultMappings: true })
      expect(responses[0].options.json).toMatchObject({
        api_key: undefined,
        events: expect.arrayContaining([
          expect.objectContaining({
            platform: 'Web'
          })
        ])
      })
    })

    it('should set Platform field to value passed by customer when Library field = "analytics.js" and Platform field is not null or undefined', async () => {
      const event = createTestEvent({
        event: 'Test Event',
        context: {
          device: {
            id: 'foo',
            type: 'Some_Custom_Platform_Value'
          },
          library: {
            name: 'analytics.js',
            version: '2.11.1'
          }
        }
      })

      nock('https://api2.amplitude.com/2').post('/httpapi').reply(200, {})

      const responses = await testDestination.testAction('logPurchase', { event, useDefaultMappings: true })
      expect(responses[0].options.json).toMatchObject({
        api_key: undefined,
        events: expect.arrayContaining([
          expect.objectContaining({
            platform: 'Some_Custom_Platform_Value'
          })
        ])
      })
    })

    it('should accept null for user_id', async () => {
      const event = createTestEvent({ timestamp, userId: null, event: 'Null User' })

      nock('https://api2.amplitude.com/2').post('/httpapi').reply(200, {})

      const responses = await testDestination.testAction('logPurchase', { event, useDefaultMappings: true })
      expect(responses.length).toBe(1)
      expect(responses[0].status).toBe(200)
      expect(responses[0].data).toMatchObject({})
      expect(responses[0].options.json).toMatchObject({
        api_key: undefined,
        events: expect.arrayContaining([
          expect.objectContaining({
            event_type: 'Null User',
            user_id: null
          })
        ])
      })
    })

    it('should work with default mappings', async () => {
      const event = createTestEvent({
        event: 'Order Completed',
        timestamp,
        properties: {
          revenue: 1_999,
          products: [
            {
              quantity: 1,
              productId: 'Bowflex Treadmill 10',
              price: 1_999
            }
          ]
        }
      })

      nock('https://api2.amplitude.com/2').post('/httpapi').reply(200, {})

      const responses = await testDestination.testAction('logPurchase', { event, useDefaultMappings: true })
      expect(responses.length).toBe(1)
      expect(responses[0].status).toBe(200)
      expect(responses[0].options.json).toMatchObject({
        api_key: undefined,
        events: expect.arrayContaining([
          expect.objectContaining({
            event_type: 'Order Completed',
            revenue: 1_999,
            event_properties: event.properties,
            library: 'segment'
          }),
          expect.objectContaining({
            event_type: 'Product Purchased',
            // @ts-ignore i know what i'm doing
            event_properties: event.properties.products[0],
            library: 'segment'
          })
        ])
      })
    })

    it('should allow alternate revenue names at the root level', async () => {
      //understand that this is basically just testing mapping kit which is already tested
      nock('https://api2.amplitude.com/2').post('/httpapi').reply(200, {})

      const event = createTestEvent({
        event: 'Order Completed',
        timestamp,
        properties: {
          revenue: 1_999,
          bitcoin_rev: 9_999
        }
      })

      const mapping = {
        revenue: {
          '@path': '$.properties.bitcoin_rev'
        }
      }

      const responses = await testDestination.testAction('logPurchase', { event, mapping, useDefaultMappings: true })
      expect(responses.length).toBe(1)
      expect(responses[0].status).toBe(200)
      expect(responses[0].options.json).toMatchObject({
        api_key: undefined,
        events: expect.arrayContaining([
          expect.objectContaining({
            event_type: 'Order Completed',
            event_properties: event.properties,
            revenue: 9_999
          })
        ])
      })
    })

    it('should work with per product revenue tracking', async () => {
      nock('https://api2.amplitude.com/2').post('/httpapi').reply(200, {})

      const event = createTestEvent({
        event: 'Order Completed',
        timestamp,
        properties: {
          revenue: 1_999,
          products: [
            {
              quantity: 1,
              productId: 'Bowflex Treadmill 10',
              revenue: 500
            }
          ]
        }
      })

      const mapping = {
        trackRevenuePerProduct: true
      }

      const responses = await testDestination.testAction('logPurchase', { event, mapping, useDefaultMappings: true })
      expect(responses.length).toBe(1)
      expect(responses[0].status).toBe(200)
      expect(responses[0].options.json).toMatchObject({
        api_key: undefined,
        events: expect.arrayContaining([
          expect.objectContaining({
            event_type: 'Order Completed',
            event_properties: event.properties
          }),
          expect.objectContaining({
            event_type: 'Product Purchased',
            revenue: 500,
            // @ts-ignore i know what i'm doing
            event_properties: event.properties.products[0]
          })
        ])
      })
    })

    it('should not inject userData if the default mapping is not satisfied and utm / referrer are not provided', async () => {
      const event = createTestEvent({
        timestamp,
        event: 'Test Event',
        traits: {
          'some-trait-key': 'some-trait-value'
        },
        context: {
          'some-context': 'yep'
        }
      })
      nock('https://api2.amplitude.com/2').post('/httpapi').reply(200, {})
      const responses = await testDestination.testAction('logPurchase', { event, useDefaultMappings: true })
      expect(responses.length).toBe(1)
      expect(responses[0].status).toBe(200)
      expect(responses[0].data).toMatchObject({})

      expect(responses[0].options.json).toMatchObject({
        events: expect.arrayContaining([
          expect.objectContaining({
            event_type: 'Test Event',
            event_properties: {},
            user_properties: {
              'some-trait-key': 'some-trait-value'
            },
            use_batch_endpoint: false
          })
        ])
      })
    })

    it('should support referrer and utm properties in logPurchase call to amplitude', async () => {
      const event = createTestEvent({
        timestamp,
        event: 'Test Event',
        traits: {
          'some-trait-key': 'some-trait-value'
        },
        context: {
          page: {
            referrer: 'some-referrer'
          },
          campaign: {
            name: 'TPS Innovation Newsletter',
            source: 'Newsletter',
            medium: 'email',
            term: 'tps reports',
            content: 'image link'
          }
        }
      })
      nock('https://api2.amplitude.com/2').post('/httpapi').reply(200, {})
      const responses = await testDestination.testAction('logPurchase', { event, useDefaultMappings: true })
      expect(responses.length).toBe(1)
      expect(responses[0].status).toBe(200)
      expect(responses[0].data).toMatchObject({})
      expect(responses[0].options.json).toMatchObject({
        api_key: undefined,
        events: expect.arrayContaining([
          expect.objectContaining({
            event_type: 'Test Event',
            user_properties: expect.objectContaining({
              'some-trait-key': 'some-trait-value',
              $set: {
                utm_source: 'Newsletter',
                utm_medium: 'email',
                utm_campaign: 'TPS Innovation Newsletter',
                utm_term: 'tps reports',
                utm_content: 'image link',
                referrer: 'some-referrer'
              },
              $setOnce: {
                initial_utm_source: 'Newsletter',
                initial_utm_medium: 'email',
                initial_utm_campaign: 'TPS Innovation Newsletter',
                initial_utm_term: 'tps reports',
                initial_utm_content: 'image link',
                initial_referrer: 'some-referrer'
              }
            })
          })
        ])
      })
    })

    it('should support parsing userAgent when the setting is true', async () => {
      const event = createTestEvent({
        anonymousId: '6fd32a7e-3c56-44c2-bd32-62bbec44c53d',
        timestamp,
        event: 'Test Event',
        context: {
          userAgent:
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/53.0.2785.143 Safari/537.36'
        }
      })
      const mapping = {
        userAgentParsing: true
      }
      nock('https://api2.amplitude.com/2').post('/httpapi').reply(200, {})
      const responses = await testDestination.testAction('logPurchase', { event, mapping, useDefaultMappings: true })
      expect(responses.length).toBe(1)
      expect(responses[0].status).toBe(200)
      expect(responses[0].data).toMatchObject({})
      expect(responses[0].options.json).toMatchInlineSnapshot(`
        Object {
          "api_key": undefined,
          "events": Array [
            Object {
              "device_id": "6fd32a7e-3c56-44c2-bd32-62bbec44c53d",
              "device_manufacturer": undefined,
              "device_model": "Mac OS",
              "device_type": undefined,
              "event_properties": Object {},
              "event_type": "Test Event",
              "library": "segment",
              "os_name": "Mac OS",
              "os_version": "53",
              "time": 1629213675449,
              "use_batch_endpoint": false,
              "user_id": "user1234",
              "user_properties": Object {},
            },
          ],
          "options": undefined,
        }
      `)
    })

    it('should support session_id from `integrations.Actions Amplitude.session_id`', async () => {
      const event = createTestEvent({
        timestamp,
        event: 'Test Event',
        anonymousId: 'julio',
        integrations: {
          // @ts-expect-error integrations should accept complex objects;
          'Actions Amplitude': {
            session_id: '1234567890'
          }
        }
      })

      nock('https://api2.amplitude.com/2').post('/httpapi').reply(200, {})

      const responses = await testDestination.testAction('logPurchase', { event, useDefaultMappings: true })

      expect(responses.length).toBe(1)
      expect(responses[0].status).toBe(200)
      expect(responses[0].data).toMatchObject({})

      expect(responses[0].options.json).toMatchInlineSnapshot(`
        Object {
          "api_key": undefined,
          "events": Array [
            Object {
              "city": "San Francisco",
              "country": "United States",
              "device_id": "julio",
              "device_manufacturer": "Apple",
              "device_model": "iPhone",
              "device_type": "mobile",
              "event_properties": Object {},
              "event_type": "Test Event",
              "ip": "8.8.8.8",
              "language": "en-US",
              "library": "segment",
              "location_lat": 40.2964197,
              "location_lng": -76.9411617,
              "os_name": "iOS",
              "os_version": "9",
              "platform": "Web",
              "session_id": 1234567890,
              "time": 1629213675449,
              "use_batch_endpoint": false,
              "user_id": "user1234",
              "user_properties": Object {},
            },
          ],
          "options": undefined,
        }
      `)
    })

    it('supports session_id from `integrations.Actions Amplitude.session_id` in number format', async () => {
      const event = createTestEvent({
        timestamp,
        event: 'Test Event',
        anonymousId: 'julio',
        integrations: {
          // @ts-expect-error integrations should accept complex objects;
          'Actions Amplitude': {
            session_id: 1234567890
          }
        }
      })

      nock('https://api2.amplitude.com/2').post('/httpapi').reply(200, {})

      const responses = await testDestination.testAction('logPurchase', { event, useDefaultMappings: true })

      expect(responses.length).toBe(1)
      expect(responses[0].status).toBe(200)
      expect(responses[0].data).toMatchObject({})

      expect(responses[0].options.json).toMatchInlineSnapshot(`
        Object {
          "api_key": undefined,
          "events": Array [
            Object {
              "city": "San Francisco",
              "country": "United States",
              "device_id": "julio",
              "device_manufacturer": "Apple",
              "device_model": "iPhone",
              "device_type": "mobile",
              "event_properties": Object {},
              "event_type": "Test Event",
              "ip": "8.8.8.8",
              "language": "en-US",
              "library": "segment",
              "location_lat": 40.2964197,
              "location_lng": -76.9411617,
              "os_name": "iOS",
              "os_version": "9",
              "platform": "Web",
              "session_id": 1234567890,
              "time": 1629213675449,
              "use_batch_endpoint": false,
              "user_id": "user1234",
              "user_properties": Object {},
            },
          ],
          "options": undefined,
        }
      `)
    })

    it('should send data to the EU endpoint', async () => {
      const event = createTestEvent({ timestamp, event: 'Test Event' })

      nock('https://api.eu.amplitude.com/2').post('/httpapi').reply(200, {})
      const responses = await testDestination.testAction('logPurchase', {
        event,
        useDefaultMappings: true,
        settings: {
          apiKey: '',
          secretKey: '',
          endpoint: 'europe'
        }
      })
      expect(responses.length).toBe(1)
      expect(responses[0].status).toBe(200)
      expect(responses[0].data).toMatchObject({})
      expect(responses[0].options.json).toMatchObject({
        api_key: '',
        events: expect.arrayContaining([
          expect.objectContaining({
            event_type: 'Test Event',
            city: 'San Francisco',
            country: 'United States'
          })
        ])
      })
    })

    it('should send data to the batch EU endpoint when specified in settings', async () => {
      const event = createTestEvent({
        timestamp,
        event: 'Test Event'
      })

      nock('https://api.eu.amplitude.com').post('/batch').reply(200, {})
      const responses = await testDestination.testAction('logPurchase', {
        event,
        useDefaultMappings: true,
        settings: {
          apiKey: '',
          secretKey: '',
          endpoint: 'europe'
        },
        mapping: {
          use_batch_endpoint: true
        }
      })
      expect(responses.length).toBe(1)
      expect(responses[0].status).toBe(200)
      expect(responses[0].data).toMatchObject({})
      expect(responses[0].options.json).toMatchObject({
        api_key: '',
        events: expect.arrayContaining([
          expect.objectContaining({
            event_type: 'Test Event',
            city: 'San Francisco',
            country: 'United States'
          })
        ])
      })
    })

    it('should give precedence to OS properties over userAgent properties', async () => {
      const event = createTestEvent({
        anonymousId: '6fd32a7e-3c56-44c2-bd32-62bbec44c53d',
        timestamp,
        event: 'Test Event',
        context: {
          os: {
            name: 'iPhone OS',
            version: '8.1.3'
          },
          userAgent:
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/53.0.2785.143 Safari/537.36'
        }
      })
      const mapping = {
        userAgentParsing: true
      }
      nock('https://api2.amplitude.com/2').post('/httpapi').reply(200, {})
      const responses = await testDestination.testAction('logPurchase', { event, mapping, useDefaultMappings: true })
      expect(responses.length).toBe(1)
      expect(responses[0].status).toBe(200)
      expect(responses[0].data).toMatchObject({})
      expect(responses[0].options.json).toMatchInlineSnapshot(`
        Object {
          "api_key": undefined,
          "events": Array [
            Object {
              "device_id": "6fd32a7e-3c56-44c2-bd32-62bbec44c53d",
              "device_manufacturer": undefined,
              "device_model": "Mac OS",
              "device_type": undefined,
              "event_properties": Object {},
              "event_type": "Test Event",
              "library": "segment",
              "os_name": "iPhone OS",
              "os_version": "8.1.3",
              "time": 1629213675449,
              "use_batch_endpoint": false,
              "user_id": "user1234",
              "user_properties": Object {},
            },
          ],
          "options": undefined,
        }
      `)
    })

    it('should calculate revenue based on price and quantity', async () => {
      const event = createTestEvent({
        event: 'Order Completed',
        timestamp,
        properties: {
          revenue: 3_998,
          products: [
            {
              quantity: 2,
              productId: 'Bowflex Treadmill 10',
              price: 1_999
            }
          ]
        }
      })

      const mapping = {
        trackRevenuePerProduct: true
      }

      nock('https://api2.amplitude.com/2').post('/httpapi').reply(200, {})

      const responses = await testDestination.testAction('logPurchase', { event, mapping, useDefaultMappings: true })
      expect(responses.length).toBe(1)
      expect(responses[0].status).toBe(200)
      expect(responses[0].options.json).toMatchObject({
        api_key: undefined,
        events: expect.arrayContaining([
          expect.objectContaining({
            event_type: 'Order Completed',
            event_properties: event.properties,
            library: 'segment'
          }),
          expect.objectContaining({
            event_type: 'Product Purchased',
            revenue: 3_998,
            price: 1_999,
            quantity: 2,
            // @ts-ignore i know what i'm doing
            event_properties: event.properties.products[0],
            library: 'segment'
          })
        ])
      })
    })

    it('should ignore products with no revenue or quantity/price value', async () => {
      const event = createTestEvent({
        event: 'Order Completed',
        timestamp,
        properties: {
          products: [
            {
              quantity: 2,
              productId: 'Bowflex Treadmill 10',
              price: 1_999
            },
            {
              revenue: 1_999,
              productId: 'Bowflex Treadmill 8'
            },
            {
              productId: 'Bowflex Treadmill 4',
              price: 1_999
            },
            {
              quantity: 2,
              productId: 'Bowflex Treadmill 2'
            }
          ]
        }
      })

      const mapping = {
        trackRevenuePerProduct: true
      }

      nock('https://api2.amplitude.com/2').post('/httpapi').reply(200, {})

      const responses = await testDestination.testAction('logPurchase', { event, mapping, useDefaultMappings: true })
      expect(responses.length).toBe(1)
      expect(responses[0].status).toBe(200)
      expect(responses[0].options.json).toMatchObject({
        api_key: undefined,
        events: expect.arrayContaining([
          expect.objectContaining({
            event_type: 'Order Completed',
            event_properties: event.properties,
            library: 'segment'
          }),
          expect.objectContaining({
            event_type: 'Product Purchased',
            revenue: 3_998,
            price: 1_999,
            quantity: 2,
            // @ts-ignore i know what i'm doing
            event_properties: event.properties.products[0],
            library: 'segment'
          }),
          expect.objectContaining({
            event_type: 'Product Purchased',
            revenue: 1_999,
            // @ts-ignore i know what i'm doing
            event_properties: event.properties.products[1],
            library: 'segment'
          })
        ])
      })
    })

    it('should prioritize price*quantity over revenue value', async () => {
      const event = createTestEvent({
        event: 'Order Completed',
        timestamp,
        properties: {
          revenue: 3_998,
          products: [
            {
              quantity: 2,
              productId: 'Bowflex Treadmill 10',
              price: 1_999,
              revenue: 4_000
            }
          ]
        }
      })

      const mapping = {
        trackRevenuePerProduct: true
      }

      nock('https://api2.amplitude.com/2').post('/httpapi').reply(200, {})

      const responses = await testDestination.testAction('logPurchase', { event, mapping, useDefaultMappings: true })
      expect(responses.length).toBe(1)
      expect(responses[0].status).toBe(200)
      expect(responses[0].options.json).toMatchObject({
        api_key: undefined,
        events: expect.arrayContaining([
          expect.objectContaining({
            event_type: 'Order Completed',
            event_properties: event.properties,
            library: 'segment'
          }),
          expect.objectContaining({
            event_type: 'Product Purchased',
            revenue: 3_998,
            price: 1_999,
            quantity: 2,
            // @ts-ignore i know what i'm doing
            event_properties: event.properties.products[0],
            library: 'segment'
          })
        ])
      })
    })
  })

  describe('mapUser', () => {
    it('should work with default mappings', async () => {
      const event = createTestEvent({
        type: 'alias',
        userId: 'some-user-id',
        previousId: 'some-previous-user-id'
      })

      nock('https://api.amplitude.com').post('/usermap').reply(200, {})

      const responses = await testDestination.testAction('mapUser', { event, useDefaultMappings: true })
      expect(responses.length).toBe(1)
      expect(responses[0].status).toBe(200)
      expect(responses[0].data).toMatchObject({})
      expect(responses[0].options.body?.toString()).toMatchInlineSnapshot(
        `"api_key=undefined&mapping=%5B%7B%22user_id%22%3A%22some-previous-user-id%22%2C%22global_user_id%22%3A%22some-user-id%22%7D%5D"`
      )
    })

    it('should send data to the EU endpoint', async () => {
      const event = createTestEvent({
        type: 'alias',
        userId: 'some-user-id',
        previousId: 'some-previous-user-id'
      })

      nock('https://api.eu.amplitude.com').post('/usermap').reply(200, {})

      const responses = await testDestination.testAction('mapUser', {
        event,
        useDefaultMappings: true,
        settings: {
          apiKey: '',
          secretKey: '',
          endpoint: 'europe'
        }
      })
      expect(responses.length).toBe(1)
      expect(responses[0].status).toBe(200)
      expect(responses[0].data).toMatchObject({})
      expect(responses[0].options.body?.toString()).toMatchInlineSnapshot(
        `"api_key=&mapping=%5B%7B%22user_id%22%3A%22some-previous-user-id%22%2C%22global_user_id%22%3A%22some-user-id%22%7D%5D"`
      )
    })
  })

  describe('logEvent', () => {
    it('should work with default mappings', async () => {
      const event = createTestEvent({ timestamp, event: 'Test Event' })

      nock('https://api2.amplitude.com/2').post('/httpapi').reply(200, {})

      const responses = await testDestination.testAction('logEvent', { event, useDefaultMappings: true })
      expect(responses.length).toBe(1)
      expect(responses[0].status).toBe(200)
      expect(responses[0].data).toMatchObject({})
      expect(responses[0].options.json).toMatchObject({
        api_key: undefined,
        events: expect.arrayContaining([
          expect.objectContaining({
            event_type: 'Test Event',
            city: 'San Francisco',
            country: 'United States'
          })
        ])
      })
    })

    it('should change casing for device type when value is ios', async () => {
      const event = createTestEvent({
        event: 'Test Event',
        context: {
          device: {
            id: 'foo',
            type: 'ios'
          }
        }
      })

      nock('https://api2.amplitude.com/2').post('/httpapi').reply(200, {})

      const responses = await testDestination.testAction('logEvent', { event, useDefaultMappings: true })
      expect(responses[0].options.json).toMatchObject({
        api_key: undefined,
        events: expect.arrayContaining([
          expect.objectContaining({
            device_id: 'foo',
            platform: 'iOS'
          })
        ])
      })
    })

    it('should change casing for device type when value is android', async () => {
      const event = createTestEvent({
        event: 'Test Event',
        context: {
          device: {
            id: 'foo',
            type: 'android'
          }
        }
      })

      nock('https://api2.amplitude.com/2').post('/httpapi').reply(200, {})

      const responses = await testDestination.testAction('logEvent', { event, useDefaultMappings: true })
      expect(responses[0].options.json).toMatchObject({
        api_key: undefined,
        events: expect.arrayContaining([
          expect.objectContaining({
            device_id: 'foo',
            platform: 'Android'
          })
        ])
      })
    })

    it('should accept null for user_id', async () => {
      const event = createTestEvent({ timestamp, userId: null, event: 'Null User' })

      nock('https://api2.amplitude.com/2').post('/httpapi').reply(200, {})

      const responses = await testDestination.testAction('logEvent', { event, useDefaultMappings: true })
      expect(responses.length).toBe(1)
      expect(responses[0].status).toBe(200)
      expect(responses[0].data).toMatchObject({})
      expect(responses[0].options.json).toMatchObject({
        api_key: undefined,
        events: expect.arrayContaining([
          expect.objectContaining({
            event_type: 'Null User',
            user_id: null
          })
        ])
      })
    })

    it('should work with default mappings without generating additional events from products array', async () => {
      const event = createTestEvent({
        event: 'Order Completed',
        timestamp,
        properties: {
          revenue: 1_999,
          products: [
            {
              quantity: 1,
              productId: 'Bowflex Treadmill 10',
              price: 1_999
            }
          ]
        }
      })

      nock('https://api2.amplitude.com/2').post('/httpapi').reply(200, {})

      const responses = await testDestination.testAction('logEvent', { event, useDefaultMappings: true })
      expect(responses.length).toBe(1)
      expect(responses[0].status).toBe(200)
      expect(responses[0].options.json).toMatchObject({
        api_key: undefined,
        events: expect.arrayContaining([
          expect.objectContaining({
            event_type: 'Order Completed',
            event_properties: event.properties,
            library: 'segment'
          })
        ])
      })
    })

    it('should allow alternate revenue names at the root level', async () => {
      //understand that this is basically just testing mapping kit which is already tested
      nock('https://api2.amplitude.com/2').post('/httpapi').reply(200, {})

      const event = createTestEvent({
        event: 'Order Completed',
        timestamp,
        properties: {
          revenue: 1_999,
          bitcoin_rev: 9_999
        }
      })

      const mapping = {
        revenue: {
          '@path': '$.properties.bitcoin_rev'
        }
      }

      const responses = await testDestination.testAction('logEvent', { event, mapping, useDefaultMappings: true })
      expect(responses.length).toBe(1)
      expect(responses[0].status).toBe(200)
      expect(responses[0].options.json).toMatchObject({
        api_key: undefined,
        events: expect.arrayContaining([
          expect.objectContaining({
            event_type: 'Order Completed',
            event_properties: event.properties
          })
        ])
      })
    })

    it('should not inject userData if the default mapping is not satisfied and utm / referrer are not provided', async () => {
      const event = createTestEvent({
        timestamp,
        event: 'Test Event',
        traits: {
          'some-trait-key': 'some-trait-value'
        },
        context: {
          'some-context': 'yep'
        }
      })
      nock('https://api2.amplitude.com/2').post('/httpapi').reply(200, {})
      const responses = await testDestination.testAction('logEvent', { event, useDefaultMappings: true })
      expect(responses.length).toBe(1)
      expect(responses[0].status).toBe(200)
      expect(responses[0].data).toMatchObject({})

      expect(responses[0].options.json).toMatchObject({
        events: expect.arrayContaining([
          expect.objectContaining({
            event_type: 'Test Event',
            event_properties: {},
            user_properties: {
              'some-trait-key': 'some-trait-value'
            },
            use_batch_endpoint: false
          })
        ])
      })
    })

    it('should support referrer and utm properties in logEvent call to amplitude', async () => {
      const event = createTestEvent({
        timestamp,
        event: 'Test Event',
        traits: {
          'some-trait-key': 'some-trait-value'
        },
        context: {
          page: {
            referrer: 'some-referrer'
          },
          campaign: {
            name: 'TPS Innovation Newsletter',
            source: 'Newsletter',
            medium: 'email',
            term: 'tps reports',
            content: 'image link'
          }
        }
      })
      nock('https://api2.amplitude.com/2').post('/httpapi').reply(200, {})
      const responses = await testDestination.testAction('logEvent', { event, useDefaultMappings: true })
      expect(responses.length).toBe(1)
      expect(responses[0].status).toBe(200)
      expect(responses[0].data).toMatchObject({})
      expect(responses[0].options.json).toMatchObject({
        api_key: undefined,
        events: expect.arrayContaining([
          expect.objectContaining({
            event_type: 'Test Event',
            user_properties: expect.objectContaining({
              'some-trait-key': 'some-trait-value',
              $set: {
                utm_source: 'Newsletter',
                utm_medium: 'email',
                utm_campaign: 'TPS Innovation Newsletter',
                utm_term: 'tps reports',
                utm_content: 'image link',
                referrer: 'some-referrer'
              },
              $setOnce: {
                initial_utm_source: 'Newsletter',
                initial_utm_medium: 'email',
                initial_utm_campaign: 'TPS Innovation Newsletter',
                initial_utm_term: 'tps reports',
                initial_utm_content: 'image link',
                initial_referrer: 'some-referrer'
              }
            })
          })
        ])
      })
    })

    it('should support parsing userAgent when the setting is true', async () => {
      const event = createTestEvent({
        anonymousId: '6fd32a7e-3c56-44c2-bd32-62bbec44c53d',
        timestamp,
        event: 'Test Event',
        context: {
          userAgent:
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/53.0.2785.143 Safari/537.36'
        }
      })
      const mapping = {
        userAgentParsing: true
      }
      nock('https://api2.amplitude.com/2').post('/httpapi').reply(200, {})
      const responses = await testDestination.testAction('logEvent', { event, mapping, useDefaultMappings: true })
      expect(responses.length).toBe(1)
      expect(responses[0].status).toBe(200)
      expect(responses[0].data).toMatchObject({})
      expect(responses[0].options.json).toMatchInlineSnapshot(`
        Object {
          "api_key": undefined,
          "events": Array [
            Object {
              "device_id": "6fd32a7e-3c56-44c2-bd32-62bbec44c53d",
              "device_manufacturer": undefined,
              "device_model": "Mac OS",
              "device_type": undefined,
              "event_properties": Object {},
              "event_type": "Test Event",
              "library": "segment",
              "os_name": "Mac OS",
              "os_version": "53",
              "time": 1629213675449,
              "use_batch_endpoint": false,
              "user_id": "user1234",
              "user_properties": Object {},
            },
          ],
          "options": undefined,
        }
      `)
    })

    it('should support session_id from `integrations.Actions Amplitude.session_id`', async () => {
      const event = createTestEvent({
        timestamp,
        event: 'Test Event',
        anonymousId: 'julio',
        integrations: {
          // @ts-expect-error integrations should accept complex objects;
          'Actions Amplitude': {
            session_id: '1234567890'
          }
        }
      })

      nock('https://api2.amplitude.com/2').post('/httpapi').reply(200, {})

      const responses = await testDestination.testAction('logEvent', { event, useDefaultMappings: true })

      expect(responses.length).toBe(1)
      expect(responses[0].status).toBe(200)
      expect(responses[0].data).toMatchObject({})

      expect(responses[0].options.json).toMatchInlineSnapshot(`
        Object {
          "api_key": undefined,
          "events": Array [
            Object {
              "city": "San Francisco",
              "country": "United States",
              "device_id": "julio",
              "device_manufacturer": "Apple",
              "device_model": "iPhone",
              "device_type": "mobile",
              "event_properties": Object {},
              "event_type": "Test Event",
              "ip": "8.8.8.8",
              "language": "en-US",
              "library": "segment",
              "location_lat": 40.2964197,
              "location_lng": -76.9411617,
              "os_name": "iOS",
              "os_version": "9",
              "platform": "Web",
              "session_id": 1234567890,
              "time": 1629213675449,
              "use_batch_endpoint": false,
              "user_id": "user1234",
              "user_properties": Object {},
            },
          ],
          "options": undefined,
        }
      `)
    })

    it('supports session_id from `integrations.Actions Amplitude.session_id` in number format', async () => {
      const event = createTestEvent({
        timestamp,
        event: 'Test Event',
        anonymousId: 'julio',
        integrations: {
          // @ts-expect-error integrations should accept complex objects;
          'Actions Amplitude': {
            session_id: 1234567890
          }
        }
      })

      nock('https://api2.amplitude.com/2').post('/httpapi').reply(200, {})

      const responses = await testDestination.testAction('logEvent', { event, useDefaultMappings: true })

      expect(responses.length).toBe(1)
      expect(responses[0].status).toBe(200)
      expect(responses[0].data).toMatchObject({})

      expect(responses[0].options.json).toMatchInlineSnapshot(`
        Object {
          "api_key": undefined,
          "events": Array [
            Object {
              "city": "San Francisco",
              "country": "United States",
              "device_id": "julio",
              "device_manufacturer": "Apple",
              "device_model": "iPhone",
              "device_type": "mobile",
              "event_properties": Object {},
              "event_type": "Test Event",
              "ip": "8.8.8.8",
              "language": "en-US",
              "library": "segment",
              "location_lat": 40.2964197,
              "location_lng": -76.9411617,
              "os_name": "iOS",
              "os_version": "9",
              "platform": "Web",
              "session_id": 1234567890,
              "time": 1629213675449,
              "use_batch_endpoint": false,
              "user_id": "user1234",
              "user_properties": Object {},
            },
          ],
          "options": undefined,
        }
      `)
    })

    it('should send data to the EU endpoint', async () => {
      const event = createTestEvent({ timestamp, event: 'Test Event' })

      nock('https://api.eu.amplitude.com/2').post('/httpapi').reply(200, {})
      const responses = await testDestination.testAction('logEvent', {
        event,
        useDefaultMappings: true,
        settings: {
          apiKey: '',
          secretKey: '',
          endpoint: 'europe'
        }
      })
      expect(responses.length).toBe(1)
      expect(responses[0].status).toBe(200)
      expect(responses[0].data).toMatchObject({})
      expect(responses[0].options.json).toMatchObject({
        api_key: '',
        events: expect.arrayContaining([
          expect.objectContaining({
            event_type: 'Test Event',
            city: 'San Francisco',
            country: 'United States'
          })
        ])
      })
    })

    it('should send data to the batch EU endpoint when specified in settings', async () => {
      const event = createTestEvent({
        timestamp,
        event: 'Test Event'
      })

      nock('https://api.eu.amplitude.com').post('/batch').reply(200, {})
      const responses = await testDestination.testAction('logEvent', {
        event,
        useDefaultMappings: true,
        settings: {
          apiKey: '',
          secretKey: '',
          endpoint: 'europe'
        },
        mapping: {
          use_batch_endpoint: true
        }
      })
      expect(responses.length).toBe(1)
      expect(responses[0].status).toBe(200)
      expect(responses[0].data).toMatchObject({})
      expect(responses[0].options.json).toMatchObject({
        api_key: '',
        events: expect.arrayContaining([
          expect.objectContaining({
            event_type: 'Test Event',
            city: 'San Francisco',
            country: 'United States'
          })
        ])
      })
    })

    it('should give precedence to OS properties over userAgent properties', async () => {
      const event = createTestEvent({
        anonymousId: '6fd32a7e-3c56-44c2-bd32-62bbec44c53d',
        timestamp,
        event: 'Test Event',
        context: {
          os: {
            name: 'iPhone OS',
            version: '8.1.3'
          },
          userAgent:
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/53.0.2785.143 Safari/537.36'
        }
      })
      const mapping = {
        userAgentParsing: true
      }
      nock('https://api2.amplitude.com/2').post('/httpapi').reply(200, {})
      const responses = await testDestination.testAction('logEvent', { event, mapping, useDefaultMappings: true })
      expect(responses.length).toBe(1)
      expect(responses[0].status).toBe(200)
      expect(responses[0].data).toMatchObject({})
      expect(responses[0].options.json).toMatchInlineSnapshot(`
        Object {
          "api_key": undefined,
          "events": Array [
            Object {
              "device_id": "6fd32a7e-3c56-44c2-bd32-62bbec44c53d",
              "device_manufacturer": undefined,
              "device_model": "Mac OS",
              "device_type": undefined,
              "event_properties": Object {},
              "event_type": "Test Event",
              "library": "segment",
              "os_name": "iPhone OS",
              "os_version": "8.1.3",
              "time": 1629213675449,
              "use_batch_endpoint": false,
              "user_id": "user1234",
              "user_properties": Object {},
            },
          ],
          "options": undefined,
        }
      `)
    })
  })

  describe('logEvent V2', () => {
    it('works with default mappings', async () => {
      const event = createTestEvent({ timestamp, event: 'Test Event' })

      nock('https://api2.amplitude.com/2').post('/httpapi').reply(200, {})

      const responses = await testDestination.testAction('logEventV2', { event, useDefaultMappings: true })
      expect(responses.length).toBe(1)
      expect(responses[0].status).toBe(200)
      expect(responses[0].data).toMatchObject({})
      expect(responses[0].options.json).toMatchObject({
        api_key: undefined,
        events: expect.arrayContaining([
          expect.objectContaining({
            event_type: 'Test Event',
            city: 'San Francisco',
            country: 'United States'
          })
        ])
      })
    })

    it('changes casing for device type when value is ios', async () => {
      const event = createTestEvent({
        event: 'Test Event',
        context: {
          device: {
            id: 'foo',
            type: 'ios'
          }
        }
      })

      nock('https://api2.amplitude.com/2').post('/httpapi').reply(200, {})

      const responses = await testDestination.testAction('logEventV2', { event, useDefaultMappings: true })
      expect(responses[0].options.json).toMatchObject({
        api_key: undefined,
        events: expect.arrayContaining([
          expect.objectContaining({
            device_id: 'foo',
            platform: 'iOS'
          })
        ])
      })
    })

    it('changes casing for device type when value is android', async () => {
      const event = createTestEvent({
        event: 'Test Event',
        context: {
          device: {
            id: 'foo',
            type: 'android'
          }
        }
      })

      nock('https://api2.amplitude.com/2').post('/httpapi').reply(200, {})

      const responses = await testDestination.testAction('logEventV2', { event, useDefaultMappings: true })
      expect(responses[0].options.json).toMatchObject({
        api_key: undefined,
        events: expect.arrayContaining([
          expect.objectContaining({
            device_id: 'foo',
            platform: 'Android'
          })
        ])
      })
    })

    it('accepts null for user_id', async () => {
      const event = createTestEvent({ timestamp, userId: null, event: 'Null User' })

      nock('https://api2.amplitude.com/2').post('/httpapi').reply(200, {})

      const responses = await testDestination.testAction('logEventV2', { event, useDefaultMappings: true })
      expect(responses.length).toBe(1)
      expect(responses[0].status).toBe(200)
      expect(responses[0].data).toMatchObject({})
      expect(responses[0].options.json).toMatchObject({
        api_key: undefined,
        events: expect.arrayContaining([
          expect.objectContaining({
            event_type: 'Null User',
            user_id: null
          })
        ])
      })
    })

    it('works with default mappings without generating additional events from products array', async () => {
      const event = createTestEvent({
        event: 'Order Completed',
        timestamp,
        properties: {
          revenue: 1_999,
          products: [
            {
              quantity: 1,
              productId: 'Bowflex Treadmill 10',
              price: 1_999
            }
          ]
        }
      })

      nock('https://api2.amplitude.com/2').post('/httpapi').reply(200, {})

      const responses = await testDestination.testAction('logEventV2', { event, useDefaultMappings: true })
      expect(responses.length).toBe(1)
      expect(responses[0].status).toBe(200)
      expect(responses[0].options.json).toMatchObject({
        api_key: undefined,
        events: expect.arrayContaining([
          expect.objectContaining({
            event_type: 'Order Completed',
            event_properties: event.properties,
            library: 'segment'
          })
        ])
      })
    })

    it('allows alternate revenue names at the root level', async () => {
      //understand that this is basically just testing mapping kit which is already tested
      nock('https://api2.amplitude.com/2').post('/httpapi').reply(200, {})

      const event = createTestEvent({
        event: 'Order Completed',
        timestamp,
        properties: {
          revenue: 1_999,
          bitcoin_rev: 9_999
        }
      })

      const mapping = {
        revenue: {
          '@path': '$.properties.bitcoin_rev'
        }
      }

      const responses = await testDestination.testAction('logEventV2', { event, mapping, useDefaultMappings: true })
      expect(responses.length).toBe(1)
      expect(responses[0].status).toBe(200)
      expect(responses[0].options.json).toMatchObject({
        api_key: undefined,
        events: expect.arrayContaining([
          expect.objectContaining({
            event_type: 'Order Completed',
            event_properties: event.properties
          })
        ])
      })
    })

    it('does not inject userData if the default mapping is not satisfied and utm / referrer are not provided', async () => {
      const event = createTestEvent({
        timestamp,
        event: 'Test Event',
        traits: {
          'some-trait-key': 'some-trait-value'
        },
        context: {
          'some-context': 'yep'
        }
      })
      nock('https://api2.amplitude.com/2').post('/httpapi').reply(200, {})
      const responses = await testDestination.testAction('logEventV2', { event, useDefaultMappings: true })
      expect(responses.length).toBe(1)
      expect(responses[0].status).toBe(200)
      expect(responses[0].data).toMatchObject({})

      expect(responses[0].options.json).toMatchObject({
        events: expect.arrayContaining([
          expect.objectContaining({
            event_type: 'Test Event',
            event_properties: {},
            user_properties: {
              'some-trait-key': 'some-trait-value'
            },
            use_batch_endpoint: false
          })
        ])
      })
    })

    it('supports referrer and utm properties in logEvent call to amplitude', async () => {
      const event = createTestEvent({
        timestamp,
        event: 'Test Event',
        traits: {
          'some-trait-key': 'some-trait-value'
        },
        context: {
          page: {
            referrer: 'some-referrer'
          },
          campaign: {
            name: 'TPS Innovation Newsletter',
            source: 'Newsletter',
            medium: 'email',
            term: 'tps reports',
            content: 'image link'
          }
        }
      })
      nock('https://api2.amplitude.com/2').post('/httpapi').reply(200, {})
      const responses = await testDestination.testAction('logEventV2', { event, useDefaultMappings: true })
      expect(responses.length).toBe(1)
      expect(responses[0].status).toBe(200)
      expect(responses[0].data).toMatchObject({})
      expect(responses[0].options.json).toMatchObject({
        api_key: undefined,
        events: expect.arrayContaining([
          expect.objectContaining({
            event_type: 'Test Event',
            user_properties: expect.objectContaining({
              'some-trait-key': 'some-trait-value',
              $set: {
                utm_source: 'Newsletter',
                utm_medium: 'email',
                utm_campaign: 'TPS Innovation Newsletter',
                utm_term: 'tps reports',
                utm_content: 'image link',
                referrer: 'some-referrer'
              },
              $setOnce: {
                initial_utm_source: 'Newsletter',
                initial_utm_medium: 'email',
                initial_utm_campaign: 'TPS Innovation Newsletter',
                initial_utm_term: 'tps reports',
                initial_utm_content: 'image link',
                initial_referrer: 'some-referrer'
              }
            })
          })
        ])
      })
    })

    it('supports parsing userAgent when the setting is true', async () => {
      const event = createTestEvent({
        anonymousId: '6fd32a7e-3c56-44c2-bd32-62bbec44c53d',
        timestamp,
        event: 'Test Event',
        context: {
          userAgent:
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/53.0.2785.143 Safari/537.36'
        }
      })
      const mapping = {
        userAgentParsing: true
      }
      nock('https://api2.amplitude.com/2').post('/httpapi').reply(200, {})
      const responses = await testDestination.testAction('logEventV2', { event, mapping, useDefaultMappings: true })
      expect(responses.length).toBe(1)
      expect(responses[0].status).toBe(200)
      expect(responses[0].data).toMatchObject({})
      expect(responses[0].options.json).toMatchInlineSnapshot(`
        Object {
          "api_key": undefined,
          "events": Array [
            Object {
              "device_id": "6fd32a7e-3c56-44c2-bd32-62bbec44c53d",
              "device_manufacturer": undefined,
              "device_model": "Mac OS",
              "device_type": undefined,
              "event_properties": Object {},
              "event_type": "Test Event",
              "library": "segment",
              "os_name": "Mac OS",
              "os_version": "53",
              "time": 1629213675449,
              "use_batch_endpoint": false,
              "user_id": "user1234",
              "user_properties": Object {},
            },
          ],
          "options": undefined,
        }
      `)
    })

    it('supports session_id from `integrations.Actions Amplitude.session_id`', async () => {
      const event = createTestEvent({
        timestamp,
        event: 'Test Event',
        anonymousId: 'julio',
        integrations: {
          // @ts-expect-error integrations should accept complex objects;
          'Actions Amplitude': {
            session_id: '1234567890'
          }
        }
      })

      nock('https://api2.amplitude.com/2').post('/httpapi').reply(200, {})

      const responses = await testDestination.testAction('logEventV2', { event, useDefaultMappings: true })

      expect(responses.length).toBe(1)
      expect(responses[0].status).toBe(200)
      expect(responses[0].data).toMatchObject({})

      expect(responses[0].options.json).toMatchInlineSnapshot(`
        Object {
          "api_key": undefined,
          "events": Array [
            Object {
              "city": "San Francisco",
              "country": "United States",
              "device_id": "julio",
              "device_manufacturer": "Apple",
              "device_model": "iPhone",
              "device_type": "mobile",
              "event_properties": Object {},
              "event_type": "Test Event",
              "ip": "8.8.8.8",
              "language": "en-US",
              "library": "segment",
              "location_lat": 40.2964197,
              "location_lng": -76.9411617,
              "os_name": "iOS",
              "os_version": "9",
              "platform": "Web",
              "session_id": 1234567890,
              "time": 1629213675449,
              "use_batch_endpoint": false,
              "user_id": "user1234",
              "user_properties": Object {},
            },
          ],
          "options": undefined,
        }
      `)
    })

    it('supports session_id from `integrations.Actions Amplitude.session_id` in number format', async () => {
      const event = createTestEvent({
        timestamp,
        event: 'Test Event',
        anonymousId: 'julio',
        integrations: {
          // @ts-expect-error integrations should accept complex objects;
          'Actions Amplitude': {
            session_id: 1234567890
          }
        }
      })

      nock('https://api2.amplitude.com/2').post('/httpapi').reply(200, {})

      const responses = await testDestination.testAction('logEventV2', { event, useDefaultMappings: true })

      expect(responses.length).toBe(1)
      expect(responses[0].status).toBe(200)
      expect(responses[0].data).toMatchObject({})

      expect(responses[0].options.json).toMatchInlineSnapshot(`
        Object {
          "api_key": undefined,
          "events": Array [
            Object {
              "city": "San Francisco",
              "country": "United States",
              "device_id": "julio",
              "device_manufacturer": "Apple",
              "device_model": "iPhone",
              "device_type": "mobile",
              "event_properties": Object {},
              "event_type": "Test Event",
              "ip": "8.8.8.8",
              "language": "en-US",
              "library": "segment",
              "location_lat": 40.2964197,
              "location_lng": -76.9411617,
              "os_name": "iOS",
              "os_version": "9",
              "platform": "Web",
              "session_id": 1234567890,
              "time": 1629213675449,
              "use_batch_endpoint": false,
              "user_id": "user1234",
              "user_properties": Object {},
            },
          ],
          "options": undefined,
        }
      `)
    })

    it('sends data to the EU endpoint', async () => {
      const event = createTestEvent({ timestamp, event: 'Test Event' })

      nock('https://api.eu.amplitude.com/2').post('/httpapi').reply(200, {})
      const responses = await testDestination.testAction('logEventV2', {
        event,
        useDefaultMappings: true,
        settings: {
          apiKey: '',
          secretKey: '',
          endpoint: 'europe'
        }
      })
      expect(responses.length).toBe(1)
      expect(responses[0].status).toBe(200)
      expect(responses[0].data).toMatchObject({})
      expect(responses[0].options.json).toMatchObject({
        api_key: '',
        events: expect.arrayContaining([
          expect.objectContaining({
            event_type: 'Test Event',
            city: 'San Francisco',
            country: 'United States'
          })
        ])
      })
    })

    it('sends data to the batch EU endpoint when specified in settings', async () => {
      const event = createTestEvent({
        timestamp,
        event: 'Test Event'
      })

      nock('https://api.eu.amplitude.com').post('/batch').reply(200, {})
      const responses = await testDestination.testAction('logEventV2', {
        event,
        useDefaultMappings: true,
        settings: {
          apiKey: '',
          secretKey: '',
          endpoint: 'europe'
        },
        mapping: {
          use_batch_endpoint: true
        }
      })
      expect(responses.length).toBe(1)
      expect(responses[0].status).toBe(200)
      expect(responses[0].data).toMatchObject({})
      expect(responses[0].options.json).toMatchObject({
        api_key: '',
        events: expect.arrayContaining([
          expect.objectContaining({
            event_type: 'Test Event',
            city: 'San Francisco',
            country: 'United States'
          })
        ])
      })
    })

    it('correctly handles the default mappings for setOnce, setAlways, and add', async () => {
      nock('https://api2.amplitude.com/2').post('/httpapi').reply(200, {})

      const event = createTestEvent({
        timestamp,
        event: 'Test Event',
        traits: {
          'some-trait-key': 'some-trait-value'
        },
        context: {
          page: {
            referrer: 'some-referrer'
          },
          campaign: {
            name: 'TPS Innovation Newsletter',
            source: 'Newsletter',
            medium: 'email',
            term: 'tps reports',
            content: 'image link'
          }
        }
      })

      const responses = await testDestination.testAction('logEventV2', { event, useDefaultMappings: true })
      expect(responses.length).toBe(1)
      expect(responses[0].status).toBe(200)
      expect(responses[0].options.json).toMatchObject({
        api_key: undefined,
        events: expect.arrayContaining([
          expect.objectContaining({
            user_properties: expect.objectContaining({
              $set: {
                referrer: 'some-referrer',
                utm_campaign: 'TPS Innovation Newsletter',
                utm_content: 'image link',
                utm_medium: 'email',
                utm_source: 'Newsletter',
                utm_term: 'tps reports'
              },
              $setOnce: {
                initial_referrer: 'some-referrer',
                initial_utm_campaign: 'TPS Innovation Newsletter',
                initial_utm_content: 'image link',
                initial_utm_medium: 'email',
                initial_utm_source: 'Newsletter',
                initial_utm_term: 'tps reports'
              }
            })
          })
        ])
      })
    })

    it('works when setOnce, setAlways, and add are empty', async () => {
      nock('https://api2.amplitude.com/2').post('/httpapi').reply(200, {})

      const event = createTestEvent({
        timestamp,
        event: 'Test Event',
        traits: {
          'some-trait-key': 'some-trait-value'
        },
        context: {
          page: {
            referrer: 'some-referrer'
          },
          campaign: {
            name: 'TPS Innovation Newsletter',
            source: 'Newsletter',
            medium: 'email',
            term: 'tps reports',
            content: 'image link'
          }
        }
      })

      const mapping = {
        setOnce: {},
        setAlways: {},
        add: {}
      }

      const responses = await testDestination.testAction('logEventV2', { event, mapping, useDefaultMappings: true })
      expect(responses.length).toBe(1)
      expect(responses[0].status).toBe(200)
      expect(responses[0].options.json).toMatchObject({
        api_key: undefined,
        events: expect.arrayContaining([
          expect.objectContaining({
            user_properties: expect.objectContaining({
              'some-trait-key': 'some-trait-value'
            })
          })
        ])
      })
    })

    it('should give precedence to OS properties over userAgent properties', async () => {
      const event = createTestEvent({
        anonymousId: '6fd32a7e-3c56-44c2-bd32-62bbec44c53d',
        timestamp,
        event: 'Test Event',
        context: {
          os: {
            name: 'iPhone OS',
            version: '8.1.3'
          },
          userAgent:
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/53.0.2785.143 Safari/537.36'
        }
      })
      const mapping = {
        userAgentParsing: true
      }
      nock('https://api2.amplitude.com/2').post('/httpapi').reply(200, {})
      const responses = await testDestination.testAction('logEventV2', { event, mapping, useDefaultMappings: true })
      expect(responses.length).toBe(1)
      expect(responses[0].status).toBe(200)
      expect(responses[0].data).toMatchObject({})
      expect(responses[0].options.json).toMatchInlineSnapshot(`
        Object {
          "api_key": undefined,
          "events": Array [
            Object {
              "device_id": "6fd32a7e-3c56-44c2-bd32-62bbec44c53d",
              "device_manufacturer": undefined,
              "device_model": "Mac OS",
              "device_type": undefined,
              "event_properties": Object {},
              "event_type": "Test Event",
              "library": "segment",
              "os_name": "iPhone OS",
              "os_version": "8.1.3",
              "time": 1629213675449,
              "use_batch_endpoint": false,
              "user_id": "user1234",
              "user_properties": Object {},
            },
          ],
          "options": undefined,
        }
      `)
    })
  })

  it('does not send parsed user agent properties when setting is false', async () => {
    const event = createTestEvent({
      timestamp: '2021-04-12T16:32:37.710Z',
      event: 'Test Event',
      context: {
        device: {
          id: 'foo'
        },
        userAgent:
          'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/53.0.2785.143 Safari/537.36'
      }
    })
    const mapping = {
      userAgentParsing: false
    }
    nock('https://api2.amplitude.com/2').post('/httpapi').reply(200, {})
    const responses = await testDestination.testAction('logEvent', { event, mapping, useDefaultMappings: true })
    expect(responses.length).toBe(1)
    expect(responses[0].status).toBe(200)
    expect(responses[0].data).toMatchObject({})
    expect(responses[0].options.json).toMatchInlineSnapshot(`
        Object {
          "api_key": undefined,
          "events": Array [
            Object {
              "device_id": "foo",
              "event_properties": Object {},
              "event_type": "Test Event",
              "idfv": "foo",
              "library": "segment",
              "time": 1618245157710,
              "use_batch_endpoint": false,
              "user_id": "user1234",
              "user_properties": Object {},
            },
          ],
          "options": undefined,
        }
      `)
  })

  describe('identifyUser', () => {
    it('should work with default mappings', async () => {
      const event = createTestEvent({
        anonymousId: 'some-anonymous-id',
        timestamp: '2021-04-12T16:32:37.710Z',
        type: 'group',
        userId: 'some-user-id',
        traits: {
          'some-trait-key': 'some-trait-value'
        }
      })

      nock('https://api2.amplitude.com').post('/identify').reply(200, {})
      const responses = await testDestination.testAction('identifyUser', { event, useDefaultMappings: true })
      expect(responses.length).toBe(1)
      expect(responses[0].status).toBe(200)
      expect(responses[0].data).toMatchObject({})
      expect(responses[0].options.body?.toString()).toMatchInlineSnapshot(
        `"api_key=undefined&identification=%7B%22os_name%22%3A%22iOS%22%2C%22os_version%22%3A%229%22%2C%22device_manufacturer%22%3A%22Apple%22%2C%22device_model%22%3A%22iPhone%22%2C%22device_type%22%3A%22mobile%22%2C%22user_id%22%3A%22some-user-id%22%2C%22device_id%22%3A%22some-anonymous-id%22%2C%22user_properties%22%3A%7B%22some-trait-key%22%3A%22some-trait-value%22%7D%2C%22country%22%3A%22United+States%22%2C%22city%22%3A%22San+Francisco%22%2C%22language%22%3A%22en-US%22%2C%22platform%22%3A%22Web%22%2C%22library%22%3A%22segment%22%7D&options=undefined"`
      )
    })

    it('should support referrer and utm user_properties', async () => {
      const event = createTestEvent({
        anonymousId: 'some-anonymous-id',
        timestamp: '2021-04-12T16:32:37.710Z',
        type: 'group',
        userId: 'some-user-id',
        event: 'Test Event',
        traits: {
          'some-trait-key': 'some-trait-value'
        },
        context: {
          page: {
            referrer: 'some-referrer'
          },
          campaign: {
            name: 'TPS Innovation Newsletter',
            source: 'Newsletter',
            medium: 'email',
            term: 'tps reports',
            content: 'image link'
          }
        }
      })
      nock('https://api2.amplitude.com').post('/identify').reply(200, {})
      const responses = await testDestination.testAction('identifyUser', { event, useDefaultMappings: true })
      expect(responses.length).toBe(1)
      expect(responses[0].status).toBe(200)
      expect(responses[0].data).toMatchObject({})
      expect(responses[0].options.body?.toString()).toMatchInlineSnapshot(
        `"api_key=undefined&identification=%7B%22user_id%22%3A%22some-user-id%22%2C%22device_id%22%3A%22some-anonymous-id%22%2C%22user_properties%22%3A%7B%22some-trait-key%22%3A%22some-trait-value%22%2C%22%24set%22%3A%7B%22utm_source%22%3A%22Newsletter%22%2C%22utm_medium%22%3A%22email%22%2C%22utm_campaign%22%3A%22TPS+Innovation+Newsletter%22%2C%22utm_term%22%3A%22tps+reports%22%2C%22utm_content%22%3A%22image+link%22%2C%22referrer%22%3A%22some-referrer%22%7D%2C%22%24setOnce%22%3A%7B%22initial_utm_source%22%3A%22Newsletter%22%2C%22initial_utm_medium%22%3A%22email%22%2C%22initial_utm_campaign%22%3A%22TPS+Innovation+Newsletter%22%2C%22initial_utm_term%22%3A%22tps+reports%22%2C%22initial_utm_content%22%3A%22image+link%22%2C%22initial_referrer%22%3A%22some-referrer%22%7D%7D%2C%22library%22%3A%22segment%22%7D&options=undefined"`
      )
    })

    it('shouldnt append $ keys to user_properties if referrer/utm are not specified', async () => {
      const event = createTestEvent({
        anonymousId: 'some-anonymous-id',
        timestamp: '2021-04-12T16:32:37.710Z',
        type: 'group',
        userId: 'some-user-id',
        event: 'Test Event',
        traits: {
          'some-trait-key': 'some-trait-value'
        }
      })
      nock('https://api2.amplitude.com').post('/identify').reply(200, {})
      const responses = await testDestination.testAction('identifyUser', { event, useDefaultMappings: true })
      expect(responses.length).toBe(1)
      expect(responses[0].status).toBe(200)
      expect(responses[0].data).toMatchObject({})
      expect(responses[0].options.body?.toString()).toMatchInlineSnapshot(
        `"api_key=undefined&identification=%7B%22os_name%22%3A%22iOS%22%2C%22os_version%22%3A%229%22%2C%22device_manufacturer%22%3A%22Apple%22%2C%22device_model%22%3A%22iPhone%22%2C%22device_type%22%3A%22mobile%22%2C%22user_id%22%3A%22some-user-id%22%2C%22device_id%22%3A%22some-anonymous-id%22%2C%22user_properties%22%3A%7B%22some-trait-key%22%3A%22some-trait-value%22%7D%2C%22country%22%3A%22United+States%22%2C%22city%22%3A%22San+Francisco%22%2C%22language%22%3A%22en-US%22%2C%22platform%22%3A%22Web%22%2C%22library%22%3A%22segment%22%7D&options=undefined"`
      )
    })

    it('should support parsing userAgent when the setting is true', async () => {
      const event = createTestEvent({
        anonymousId: 'some-anonymous-id',
        timestamp: '2021-04-12T16:32:37.710Z',
        type: 'group',
        userId: 'some-user-id',
        event: 'Test Event',
        traits: {
          'some-trait-key': 'some-trait-value'
        },
        context: {
          device: {
            id: 'foo'
          },
          userAgent:
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/53.0.2785.143 Safari/537.36'
        }
      })

      const mapping = {
        userAgentParsing: true
      }

      nock('https://api2.amplitude.com').post('/identify').reply(200, {})
      const responses = await testDestination.testAction('identifyUser', { event, mapping, useDefaultMappings: true })
      expect(responses.length).toBe(1)
      expect(responses[0].status).toBe(200)
      expect(responses[0].data).toMatchObject({})
      expect(responses[0].options.body?.toString()).toMatchInlineSnapshot(
        `"api_key=undefined&identification=%7B%22os_name%22%3A%22Mac+OS%22%2C%22os_version%22%3A%2253%22%2C%22device_model%22%3A%22Mac+OS%22%2C%22user_id%22%3A%22some-user-id%22%2C%22device_id%22%3A%22foo%22%2C%22user_properties%22%3A%7B%22some-trait-key%22%3A%22some-trait-value%22%7D%2C%22library%22%3A%22segment%22%7D&options=undefined"`
      )
    })

    it('should not send parsed user agent properties when setting is false', async () => {
      const event = createTestEvent({
        anonymousId: 'some-anonymous-id',
        timestamp: '2021-04-12T16:32:37.710Z',
        type: 'group',
        userId: 'some-user-id',
        event: 'Test Event',
        traits: {
          'some-trait-key': 'some-trait-value'
        },
        context: {
          device: {
            id: 'foo'
          },
          userAgent:
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/53.0.2785.143 Safari/537.36'
        }
      })

      const mapping = {
        userAgentParsing: false
      }

      nock('https://api2.amplitude.com').post('/identify').reply(200, {})
      const responses = await testDestination.testAction('identifyUser', { event, mapping, useDefaultMappings: true })
      expect(responses.length).toBe(1)
      expect(responses[0].status).toBe(200)
      expect(responses[0].data).toMatchObject({})
      expect(responses[0].options.body?.toString()).toMatchInlineSnapshot(
        `"api_key=undefined&identification=%7B%22user_id%22%3A%22some-user-id%22%2C%22device_id%22%3A%22foo%22%2C%22user_properties%22%3A%7B%22some-trait-key%22%3A%22some-trait-value%22%7D%2C%22library%22%3A%22segment%22%7D&options=undefined"`
      )
    })

    it('should change casing for device type when value is android', async () => {
      const event = createTestEvent({
        context: {
          device: {
            id: 'foo',
            type: 'android'
          }
        }
      })

      const mapping = {
        userAgentParsing: false
      }

      nock('https://api2.amplitude.com').post('/identify').reply(200, {})
      const responses = await testDestination.testAction('identifyUser', { event, mapping, useDefaultMappings: true })
      expect(responses[0].options.body?.toString()).toMatchInlineSnapshot(
        `"api_key=undefined&identification=%7B%22user_id%22%3A%22user1234%22%2C%22device_id%22%3A%22foo%22%2C%22user_properties%22%3A%7B%7D%2C%22platform%22%3A%22Android%22%2C%22library%22%3A%22segment%22%7D&options=undefined"`
      )
    })

    it('should change casing for device type when value is ios', async () => {
      const event = createTestEvent({
        context: {
          device: {
            id: 'foo',
            type: 'ios'
          }
        }
      })

      const mapping = {
        userAgentParsing: false
      }

      nock('https://api2.amplitude.com').post('/identify').reply(200, {})
      const responses = await testDestination.testAction('identifyUser', { event, mapping, useDefaultMappings: true })
      expect(responses[0].options.body?.toString()).toMatchInlineSnapshot(
        `"api_key=undefined&identification=%7B%22user_id%22%3A%22user1234%22%2C%22device_id%22%3A%22foo%22%2C%22user_properties%22%3A%7B%7D%2C%22platform%22%3A%22iOS%22%2C%22library%22%3A%22segment%22%7D&options=undefined"`
      )
    })

    it('should send data to the EU endpoint', async () => {
      const event = createTestEvent({
        anonymousId: 'some-anonymous-id',
        timestamp: '2021-04-12T16:32:37.710Z',
        type: 'group',
        userId: 'some-user-id',
        traits: {
          'some-trait-key': 'some-trait-value'
        }
      })

      nock('https://api.eu.amplitude.com').post('/identify').reply(200, {})
      const responses = await testDestination.testAction('identifyUser', {
        event,
        useDefaultMappings: true,
        settings: {
          apiKey: '',
          secretKey: '',
          endpoint: 'europe'
        }
      })
      expect(responses.length).toBe(1)
      expect(responses[0].status).toBe(200)
      expect(responses[0].data).toMatchObject({})
      expect(responses[0].options.body?.toString()).toMatchInlineSnapshot(
        `"api_key=&identification=%7B%22os_name%22%3A%22iOS%22%2C%22os_version%22%3A%229%22%2C%22device_manufacturer%22%3A%22Apple%22%2C%22device_model%22%3A%22iPhone%22%2C%22device_type%22%3A%22mobile%22%2C%22user_id%22%3A%22some-user-id%22%2C%22device_id%22%3A%22some-anonymous-id%22%2C%22user_properties%22%3A%7B%22some-trait-key%22%3A%22some-trait-value%22%7D%2C%22country%22%3A%22United+States%22%2C%22city%22%3A%22San+Francisco%22%2C%22language%22%3A%22en-US%22%2C%22platform%22%3A%22Web%22%2C%22library%22%3A%22segment%22%7D&options=undefined"`
      )
    })

    it('should give precedence to OS properties over userAgent properties', async () => {
      const event = createTestEvent({
        anonymousId: 'some-anonymous-id',
        timestamp: '2021-04-12T16:32:37.710Z',
        type: 'group',
        userId: 'some-user-id',
        event: 'Test Event',
        traits: {
          'some-trait-key': 'some-trait-value'
        },
        context: {
          os: {
            name: 'iPhone OS',
            version: '8.1.3'
          },
          device: {
            id: 'foo'
          },
          userAgent:
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/53.0.2785.143 Safari/537.36'
        }
      })

      const mapping = {
        userAgentParsing: true
      }

      nock('https://api2.amplitude.com').post('/identify').reply(200, {})
      const responses = await testDestination.testAction('identifyUser', { event, mapping, useDefaultMappings: true })
      expect(responses.length).toBe(1)
      expect(responses[0].status).toBe(200)
      expect(responses[0].data).toMatchObject({})
      expect(responses[0].options.body?.toString()).toMatchInlineSnapshot(
        `"api_key=undefined&identification=%7B%22os_name%22%3A%22iPhone+OS%22%2C%22os_version%22%3A%228.1.3%22%2C%22device_model%22%3A%22Mac+OS%22%2C%22user_id%22%3A%22some-user-id%22%2C%22device_id%22%3A%22foo%22%2C%22user_properties%22%3A%7B%22some-trait-key%22%3A%22some-trait-value%22%7D%2C%22library%22%3A%22segment%22%7D&options=undefined"`
      )
    })
  })

  describe('groupIdentifyUser', () => {
    const event = createTestEvent({
      anonymousId: 'some-anonymous-id',
      timestamp: '2021-04-12T16:32:37.710Z',
      type: 'group',
      userId: 'some-user-id',
      traits: {
        'some-trait-key': 'some-trait-value'
      }
    })

    const mapping = {
      insert_id: 'some-insert-id',
      group_type: 'some-type',
      group_value: 'some-value'
    }

    it('should fire identify call to Amplitude', async () => {
      nock('https://api2.amplitude.com').post('/identify').reply(200, {})
      nock('https://api2.amplitude.com').post('/groupidentify').reply(200, {})

      const [response] = await testDestination.testAction('groupIdentifyUser', {
        event,
        mapping,
        useDefaultMappings: true
      })

      expect(response.status).toBe(200)
      expect(response.data).toMatchObject({})
      expect(response.options.body?.toString()).toMatchInlineSnapshot(
        `"api_key=undefined&identification=%5B%7B%22device_id%22%3A%22some-anonymous-id%22%2C%22groups%22%3A%7B%22some-type%22%3A%22some-value%22%7D%2C%22insert_id%22%3A%22some-insert-id%22%2C%22library%22%3A%22segment%22%2C%22time%22%3A1618245157710%2C%22user_id%22%3A%22some-user-id%22%2C%22user_properties%22%3A%7B%22some-type%22%3A%22some-value%22%7D%7D%5D&options=undefined"`
      )
    })

    it('should fire groupidentify call to Amplitude', async () => {
      nock('https://api2.amplitude.com').post('/identify').reply(200, {})
      nock('https://api2.amplitude.com').post('/groupidentify').reply(200, {})

      const [, response] = await testDestination.testAction('groupIdentifyUser', {
        event,
        mapping,
        useDefaultMappings: true
      })

      expect(response.status).toBe(200)
      expect(response.data).toMatchObject({})
      expect(response.options.body?.toString()).toMatchInlineSnapshot(
        `"api_key=undefined&identification=%5B%7B%22group_properties%22%3A%7B%22some-trait-key%22%3A%22some-trait-value%22%7D%2C%22group_value%22%3A%22some-value%22%2C%22group_type%22%3A%22some-type%22%2C%22library%22%3A%22segment%22%7D%5D&options=undefined"`
      )
    })

    it('should fire identify call to Amplitude EU endpoint', async () => {
      nock('https://api.eu.amplitude.com').post('/identify').reply(200, {})
      nock('https://api.eu.amplitude.com').post('/groupidentify').reply(200, {})

      const [response] = await testDestination.testAction('groupIdentifyUser', {
        event,
        mapping,
        useDefaultMappings: true,
        settings: {
          apiKey: '',
          secretKey: '',
          endpoint: 'europe'
        }
      })

      expect(response.status).toBe(200)
      expect(response.data).toMatchObject({})
      expect(response.options.body?.toString()).toMatchInlineSnapshot(
        `"api_key=&identification=%5B%7B%22device_id%22%3A%22some-anonymous-id%22%2C%22groups%22%3A%7B%22some-type%22%3A%22some-value%22%7D%2C%22insert_id%22%3A%22some-insert-id%22%2C%22library%22%3A%22segment%22%2C%22time%22%3A1618245157710%2C%22user_id%22%3A%22some-user-id%22%2C%22user_properties%22%3A%7B%22some-type%22%3A%22some-value%22%7D%7D%5D&options=undefined"`
      )
    })

    it('should fire groupidentify call to Amplitude EU endpoint', async () => {
      nock('https://api.eu.amplitude.com').post('/identify').reply(200, {})
      nock('https://api.eu.amplitude.com').post('/groupidentify').reply(200, {})

      const [, response] = await testDestination.testAction('groupIdentifyUser', {
        event,
        mapping,
        useDefaultMappings: true,
        settings: {
          apiKey: '',
          secretKey: '',
          endpoint: 'europe'
        }
      })

      expect(response.status).toBe(200)
      expect(response.data).toMatchObject({})
      expect(response.options.body?.toString()).toMatchInlineSnapshot(
        `"api_key=&identification=%5B%7B%22group_properties%22%3A%7B%22some-trait-key%22%3A%22some-trait-value%22%7D%2C%22group_value%22%3A%22some-value%22%2C%22group_type%22%3A%22some-type%22%2C%22library%22%3A%22segment%22%7D%5D&options=undefined"`
      )
    })
  })

  describe('deletes', () => {
    it('should support gdpr deletes', async () => {
      nock('https://amplitude.com').post('/api/2/deletions/users').reply(200, {})
      if (testDestination.onDelete) {
        const response = await testDestination.onDelete(
          { type: 'track', userId: 'sloth@segment.com' },
          { apiKey: 'foo', secretKey: 'bar' }
        )
        const resp = response as DecoratedResponse
        expect(resp.status).toBe(200)
        expect(resp.data).toMatchObject({})
      }
    })

    it('should support gdpr deletes on EU endpoint', async () => {
      nock('https://analytics.eu.amplitude.com').post('/api/2/deletions/users').reply(200, {})
      if (testDestination.onDelete) {
        const response = await testDestination.onDelete(
          { type: 'track', userId: 'sloth@segment.com' },
          { apiKey: 'foo', secretKey: 'bar', endpoint: 'europe' }
        )
        const resp = response as DecoratedResponse
        expect(resp.status).toBe(200)
        expect(resp.data).toMatchObject({})
      }
    })
  })
})

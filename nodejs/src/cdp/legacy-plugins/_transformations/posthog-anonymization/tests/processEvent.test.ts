import { PluginEvent } from '@posthog/plugin-scaffold'

import { processEvent } from '../src/processEvent'

describe('processEvent', () => {
    it('normalizes the site_url and encodes the private fields', () => {
        const siteUrl =
            'https://example.com/example.html#/path/to/resource/830baf73-2f70-4194-b18e-8900c0281f49?backUrl=return'
        /**
         * @type {Object}
         */
        const myEvent: PluginEvent = {
            event: 'visit',
            ip: '1.1.1.1',
            now: '',
            team_id: 0,
            uuid: '',
            distinct_id: '105338229',
            properties: {
                userid: '105338229',
                name: 'John Doe',
                $current_url: siteUrl,
                $set: {
                    $current_url: siteUrl,
                },
                $set_once: {
                    $initial_current_url: siteUrl,
                },
            },
        } as any

        const actual = processEvent(myEvent, {
            config: {
                salt: '1234567890',
                privateFields: 'distinct_id,userid,name',
            },
            global: {},
            logger: {
                debug: () => {},
                error: () => {},
                log: () => {},
                warn: () => {},
            },
        } as any)

        expect(actual).toMatchInlineSnapshot(`
            {
              "distinct_id": "83f029dcb4f5e8f260f008d71e770627adb92aa050aae0c005adad81cc57747c",
              "event": "visit",
              "ip": "1.1.1.1",
              "now": "",
              "properties": {
                "$current_url": "https://example.com/example.html#/path/to/resource/:id",
                "$set": {
                  "$current_url": "https://example.com/example.html#/path/to/resource/:id",
                },
                "$set_once": {
                  "$initial_current_url": "https://example.com/example.html#/path/to/resource/:id",
                },
                "name": "473fc460b53fb3c256ca124bea47e5edd337a864ec963c03ed7adcd1402cb3e7",
                "userid": "83f029dcb4f5e8f260f008d71e770627adb92aa050aae0c005adad81cc57747c",
              },
              "team_id": 0,
              "uuid": "",
            }
        `)
    })
})

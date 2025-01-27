import { processEvent } from './index'
import pluginJson from './plugin.json'

const globalConfig = Object.fromEntries(pluginJson.config.filter((c) => c.key).map((c) => [c.key, c.default]))
const makeEvent = ($pathname: string) => ({ event: '$pageview', properties: { $pathname } })

test('changes properties', () => {
    const matches = [
        ['/lol', { $pathname: '/lol' }],
        ['/english', { $pathname: '/english' }],
        ['/en', { $pathname: '/', locale: 'en' }],
        ['/en/', { $pathname: '/', locale: 'en' }],
        ['/en/?', { $pathname: '/?', locale: 'en' }],
        ['/en#bla', { $pathname: '/#bla', locale: 'en' }],
        ['/en?bla', { $pathname: '/?bla', locale: 'en' }],
        ['/en/asd', { $pathname: '/asd', locale: 'en' }],
        ['/en/en/en', { $pathname: '/en/en', locale: 'en' }],
    ]

    for (const [$pathname, properties] of matches) {
        expect(processEvent(makeEvent($pathname), { config: globalConfig }).properties).toEqual(properties)
    }
})

test('changes properties if new $pathname', () => {
    const config = { ...globalConfig, replaceKey: '$otherPath' }
    const matches = [['/en/asd', { $pathname: '/en/asd', $otherPath: '/asd', locale: 'en' }]]

    for (const [$pathname, properties] of matches) {
        expect(processEvent(makeEvent($pathname), { config }).properties).toEqual(properties)
    }
})

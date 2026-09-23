import { osFrameName } from '../bridge/osFrame'
import { osStoreInstalledChanged, osStoreOpenApp, readOsStoreMessage } from './osStoreMessages'

describe('osStoreMessages', () => {
    const page = { location: { origin: 'https://app.example.com' } } as unknown as Window
    const osWindow = { name: osFrameName('abc123'), parent: page } as unknown as Window
    const otherFrame = { name: 'embed', parent: page } as unknown as Window
    const crossOriginFrame = {
        parent: page,
        get name(): string {
            throw new Error('cross-origin')
        },
    } as unknown as Window
    const message = (data: unknown, source: Window | null, origin = 'https://app.example.com'): MessageEvent =>
        ({ data, source, origin }) as MessageEvent

    it.each([
        ['an OS window asks to reload', message(osStoreInstalledChanged(), osWindow), osStoreInstalledChanged()],
        ['an OS window asks to open an app', message(osStoreOpenApp('Surveys'), osWindow), osStoreOpenApp('Surveys')],
        ['another origin', message(osStoreOpenApp('Surveys'), osWindow, 'https://evil.example.com'), null],
        ['a frame that is not an OS window', message(osStoreOpenApp('Surveys'), otherFrame), null],
        ['a cross-origin frame', message(osStoreOpenApp('Surveys'), crossOriginFrame), null],
        ['the page itself', message(osStoreOpenApp('Surveys'), page), null],
        ['an open request without a key', message({ type: 'posthog-os-store:open-app', key: 42 }, osWindow), null],
    ])('reads %s', (_, event, expected) => {
        expect(readOsStoreMessage(event, page)).toEqual(expected)
    })
})

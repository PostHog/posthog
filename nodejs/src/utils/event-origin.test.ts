import { isProductionEventOrigin } from './event-origin'

describe('isProductionEventOrigin()', () => {
    describe('local / dev origins (must NOT fire)', () => {
        it.each([
            // No host at all — server-side SDKs, mobile, file://
            ['empty properties', {}],
            ['null $host', { $host: null }],
            ['empty $host', { $host: '' }],
            ['file:// current_url with no host', { $current_url: 'file:///Users/me/index.html' }],
            ['unparseable current_url', { $current_url: 'not a url' }],
            // localhost variants
            ['localhost', { $host: 'localhost' }],
            ['localhost with port', { $host: 'localhost:3000' }],
            ['localhost with uppercase', { $host: 'LOCALHOST:8000' }],
            ['subdomain.localhost', { $host: 'app.localhost' }],
            ['subdomain.localhost with port', { $host: 'app.localhost:3000' }],
            // loopback IPv4
            ['127.0.0.1', { $host: '127.0.0.1' }],
            ['127.0.0.1 with port', { $host: '127.0.0.1:8000' }],
            ['127.x.x.x', { $host: '127.9.9.9' }],
            ['0.0.0.0', { $host: '0.0.0.0' }],
            ['0.0.0.0 with port', { $host: '0.0.0.0:3000' }],
            // loopback / private IPv6
            ['::1', { $host: '::1' }],
            ['[::1] bracketed', { $host: '[::1]' }],
            ['[::1] bracketed with port', { $host: '[::1]:3000' }],
            ['::', { $host: '::' }],
            ['fc00 unique-local', { $host: 'fc00::1' }],
            ['fd12 unique-local', { $host: 'fd12:3456::1' }],
            ['fe80 link-local', { $host: 'fe80::1' }],
            ['[fe80::1] bracketed with port', { $host: '[fe80::1]:8080' }],
            // private IPv4 ranges
            ['10.x', { $host: '10.0.0.5' }],
            ['10.x with port', { $host: '10.1.2.3:3000' }],
            ['192.168.x', { $host: '192.168.1.10' }],
            ['172.16.x', { $host: '172.16.0.1' }],
            ['172.31.x', { $host: '172.31.255.255' }],
            ['169.254.x link-local', { $host: '169.254.1.1' }],
            // reserved/dev TLDs
            ['*.local', { $host: 'mymac.local' }],
            ['*.test', { $host: 'app.test' }],
            ['*.internal', { $host: 'service.internal' }],
            ['*.invalid', { $host: 'foo.invalid' }],
            ['*.example', { $host: 'foo.example' }],
            ['*.localdomain', { $host: 'box.localdomain' }],
            ['*.home.arpa', { $host: 'router.home.arpa' }],
            // bare single-label machine hostname
            ['bare hostname', { $host: 'my-laptop' }],
            ['bare hostname with port', { $host: 'devbox:3000' }],
            // local host derived from current_url when $host absent
            ['current_url localhost', { $current_url: 'http://localhost:3000/path' }],
            ['current_url 127.0.0.1', { $current_url: 'http://127.0.0.1:8000/' }],
            ['current_url [::1]', { $current_url: 'http://[::1]:3000/' }],
            ['current_url private ip', { $current_url: 'http://192.168.0.1/' }],
        ])('returns false for %s', (_label, properties) => {
            expect(isProductionEventOrigin(properties)).toBe(false)
        })
    })

    describe('production origins (must fire)', () => {
        it.each([
            ['public domain', { $host: 'app.posthog.com' }],
            ['public domain with port', { $host: 'app.posthog.com:443' }],
            ['public domain uppercase', { $host: 'App.PostHog.com' }],
            ['apex domain', { $host: 'posthog.com' }],
            ['deep subdomain', { $host: 'eu.dashboard.posthog.com' }],
            ['domain that merely contains "local"', { $host: 'mylocalbiz.com' }],
            ['domain that merely contains "localhost"', { $host: 'localhosting.com' }],
            ['public IPv4', { $host: '8.8.8.8' }],
            ['public IPv4 with port', { $host: '203.0.113.5:8080' }],
            ['public IPv6 bracketed', { $host: '[2001:db8::1]:443' }],
            ['public IPv6 bare', { $host: '2606:4700:4700::1111' }],
            ['172.15 just below private range', { $host: '172.15.0.1' }],
            ['172.32 just above private range', { $host: '172.32.0.1' }],
            ['production via current_url', { $current_url: 'https://app.posthog.com/insights' }],
            ['$host preferred over current_url', { $host: 'app.posthog.com', $current_url: 'http://localhost:3000' }],
        ])('returns true for %s', (_label, properties) => {
            expect(isProductionEventOrigin(properties)).toBe(true)
        })
    })
})

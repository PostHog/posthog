import { GeoIPService } from './geoip'

// Live-database canary — runs on master CI only (GEOIP_LIVE_TEST=1), against the
// GeoLite2 database that bin/download-mmdb fetched from mmdbcdn.posthog.net.
// PR runs use the pinned test fixture (see jest.setup.env.ts), so this suite is
// the safety net against a broken latest MaxMind build, e.g. the 2026-06-09
// release that blanked city/postal data for most IPs. It checks data presence,
// not exact values, so routine data updates don't fail it.
const describeLive = process.env.GEOIP_LIVE_TEST === '1' ? describe : describe.skip

// Stable ISP allocations across regions — country assignments effectively never change
const ANCHOR_IPS: { ip: string; country: string }[] = [
    { ip: '12.87.118.0', country: 'US' },
    { ip: '174.20.132.42', country: 'US' },
    { ip: '73.162.0.1', country: 'US' },
    { ip: '89.160.20.129', country: 'SE' },
    { ip: '81.2.69.142', country: 'GB' },
    { ip: '103.198.128.106', country: 'IN' },
    { ip: '185.86.151.11', country: 'GB' },
]

// A healthy build resolves city and postal for all but 0-1 anchors; the gutted
// 2026-06-09 build resolved them for only 2 of 7. Allowing 2 missing keeps
// headroom for legitimate per-IP data changes.
const MAX_MISSING = 2

describeLive('live GeoLite2 database sanity', () => {
    it('resolves anchor IPs with usable location data', async () => {
        const geoip = await new GeoIPService('../share/GeoLite2-City.mmdb').get()

        const lookups = ANCHOR_IPS.map(({ ip, country }) => {
            const res = geoip.city(ip)
            return {
                ip,
                expectedCountry: country,
                country: res?.country?.isoCode,
                hasCity: Boolean(res?.city?.names?.en),
                hasPostal: Boolean(res?.postal?.code),
            }
        })

        for (const lookup of lookups) {
            expect(lookup).toMatchObject({ country: lookup.expectedCountry })
        }

        const missingCity = lookups.filter((lookup) => !lookup.hasCity).map((lookup) => lookup.ip)
        const missingPostal = lookups.filter((lookup) => !lookup.hasPostal).map((lookup) => lookup.ip)

        if (missingCity.length > MAX_MISSING) {
            expect(missingCity).toEqual([])
        }
        if (missingPostal.length > MAX_MISSING) {
            expect(missingPostal).toEqual([])
        }
    })
})

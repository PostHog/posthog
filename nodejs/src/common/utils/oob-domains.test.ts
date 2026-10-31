import { readFileSync } from 'fs'
import path from 'path'

import { parseJSON } from './json-parse'
import { logger } from './logger'
import { OOB_DOMAINS, matchedOobDomain, noteOobDomain } from './oob-domains'

// Python reads this file at runtime, so it is the one source of truth for the list. Reading the
// file itself, rather than parsing Python, keeps the test green through a rename or a reformat on
// either side and red only when the two lists differ.
const DOMAINS_JSON = path.resolve(__dirname, '../../../../posthog/security/crosslang/oob_domains.json')

describe('oob-domains', () => {
    it('mirrors posthog/security/crosslang/oob_domains.json', () => {
        const listed: string[] = parseJSON(readFileSync(DOMAINS_JSON, 'utf8')).domains

        expect(new Set(OOB_DOMAINS)).toEqual(new Set(listed))
    })

    it.each([
        ['the listed domain itself', 'oast.me', 'oast.me'],
        ['a subdomain', 'abc123.oast.me', 'oast.me'],
        ['a deep subdomain', 'a.b.interact.sh', 'interact.sh'],
        ['an uppercase host', 'ABC.OAST.ME', 'oast.me'],
        ['an absolute host carrying the DNS root dot', 'abc.oast.me.', 'oast.me'],
        ['a host carrying more than one trailing dot', 'abc.oast.me..', 'oast.me'],
        ['the longest name DNS carries', `${'a'.repeat(245)}.oast.me`, 'oast.me'],
        ['the longest name with its root dot', `${'a'.repeat(245)}.oast.me.`, 'oast.me'],
        ['a host longer than a DNS name', `${'a'.repeat(246)}.oast.me`, null],
        ['a listed host followed by a long run of dots', `abc.oast.me${'.'.repeat(300)}`, null],
        ['a fullwidth host that IDNA maps onto a listed one', 'ｏａｓｔ．ｍｅ', 'oast.me'],
        ['a host that only ends in the same letters', 'notoast.me', null],
        ['a listed name used as a prefix', 'oast.me.evil.example', null],
        ['a listed name behind userinfo', 'user@abc.oast.me', null],
        ['a listed name behind fullwidth userinfo', 'user＠abc.oast.me', null],
        ['a listed name behind a fullwidth slash', 'user／abc.oast.me', null],
        ['a listed name behind a colon the codec rejects', 'client:secret.abc.oast.me', null],
        ['a raw URL whose path ends in a listed name', 'https://evil.example/abc.oast.me', null],
        ['an unlisted host', 'example.com', null],
        ['an empty host', '', null],
    ])('matches %s', (_description, host, expected) => {
        expect(matchedOobDomain(host)).toBe(expected)
    })

    describe('noteOobDomain', () => {
        const originalCloudDeployment = process.env.CLOUD_DEPLOYMENT
        let info: jest.SpyInstance

        beforeEach(() => {
            info = jest.spyOn(logger, 'info').mockImplementation(() => undefined)
        })

        afterEach(() => {
            info.mockRestore()
            if (originalCloudDeployment === undefined) {
                delete process.env.CLOUD_DEPLOYMENT
            } else {
                process.env.CLOUD_DEPLOYMENT = originalCloudDeployment
            }
        })

        it('logs the match with the caller attribution under the team_id the python guards bind', () => {
            process.env.CLOUD_DEPLOYMENT = 'US'

            noteOobDomain('attribution.oast.me', 'node_request', { teamId: 2 })

            expect(info).toHaveBeenCalledWith('security.oob_domain_seen', {
                team_id: 2,
                host: 'attribution.oast.me',
                domain: 'oast.me',
                guard: 'node_request',
            })
        })

        it('logs one line per host and team in the window, so a retrying caller cannot flood', () => {
            process.env.CLOUD_DEPLOYMENT = 'US'

            noteOobDomain('flood.oast.me', 'node_request', { teamId: 3 })
            noteOobDomain('flood.oast.me', 'node_request', { teamId: 3 })

            expect(info).toHaveBeenCalledTimes(1)
        })

        it('logs a second team hitting the same host, so one noisy team cannot mask another', () => {
            process.env.CLOUD_DEPLOYMENT = 'US'

            noteOobDomain('shared.oast.me', 'node_request', { teamId: 4 })
            noteOobDomain('shared.oast.me', 'node_request', { teamId: 5 })

            expect(info).toHaveBeenCalledTimes(2)
        })

        it('stays silent off cloud, so self-hosted behavior does not change', () => {
            delete process.env.CLOUD_DEPLOYMENT

            noteOobDomain('abc.oast.me', 'node_request')

            expect(info).not.toHaveBeenCalled()
        })
    })
})

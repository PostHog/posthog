import { spawnSync } from 'node:child_process'
import { resolve } from 'node:path'

import { parseJSON } from '~/common/utils/json-parse'
import { PluginEvent } from '~/plugin-scaffold'

import { LegacyTransformationPluginMeta } from '../../types'
import { processEvent } from './index'
import pluginJson from './plugin.json'

const globalConfig = Object.fromEntries(pluginJson.config.filter((c) => c.key).map((c) => [c.key, c.default]))
const makeEvent = ($pathname: string) => ({ event: '$pageview', properties: { $pathname } }) as unknown as PluginEvent

describe('language URL splitter', () => {
    test('changes properties', () => {
        const matches: [string, PluginEvent['properties']][] = [
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
            expect(
                processEvent(makeEvent($pathname), { config: globalConfig } as LegacyTransformationPluginMeta)
                    .properties
            ).toEqual(properties)
        }
    })

    test('changes properties if new $pathname', () => {
        const config = { ...globalConfig, replaceKey: '$otherPath' }
        const matches: [string, PluginEvent['properties']][] = [
            ['/en/asd', { $pathname: '/en/asd', $otherPath: '/asd', locale: 'en' }],
        ]

        for (const [$pathname, properties] of matches) {
            expect(
                processEvent(makeEvent($pathname), { config } as unknown as LegacyTransformationPluginMeta).properties
            ).toEqual(properties)
        }
    })

    test.each(['match', 'replacement'])('interrupts slow %s and can process another event', (operation) => {
        const child = spawnSync(
            process.execPath,
            [
                '-r',
                require.resolve('ts-node/register/transpile-only'),
                '-e',
                `
                const { processEvent } = require(process.argv[1])
                const config = JSON.parse(process.argv[2])
                const event = { event: '$pageview', properties: { $pathname: 'a'.repeat(128) + '!' } }
                let error
                const started = performance.now()
                try {
                    processEvent(event, { config })
                } catch (caught) {
                    error = { name: caught.name, message: caught.message, code: caught.code, isError: caught instanceof Error }
                }
                const elapsed = performance.now() - started
                const next = processEvent(
                    { event: '$pageview', properties: { $pathname: '/fr/home' } },
                    { config: { ...config, pattern: '^/([a-z]+)', replacePattern: '^/[a-z]+/', replaceValue: '/' } }
                )
                process.stdout.write(JSON.stringify({ error, elapsed, locale: event.properties.locale, next: next.properties }))
            `,
                require.resolve('./index'),
                JSON.stringify({
                    ...globalConfig,
                    pattern: operation === 'match' ? '^(a+)+$' : '^(a)',
                    replacePattern: operation === 'replacement' ? '^(a+)+$' : '',
                }),
            ],
            {
                encoding: 'utf8',
                timeout: 3000,
                killSignal: 'SIGKILL',
                env: { ...process.env, TS_NODE_PROJECT: resolve(__dirname, '../../../../..', 'tsconfig.test.json') },
            }
        )

        expect({
            status: child.status,
            signal: child.signal,
            error: child.error?.message,
            stderr: child.stderr,
        }).toEqual({
            status: 0,
            signal: null,
            error: undefined,
            stderr: '',
        })
        const result = parseJSON(child.stdout)
        expect(result.error).toEqual({
            name: 'Error',
            message: expect.stringContaining('timed out after 50ms'),
            code: 'ERR_SCRIPT_EXECUTION_TIMEOUT',
            isError: true,
        })
        expect(result.elapsed).toBeLessThan(1000)
        expect(result.locale).toBe(operation === 'replacement' ? 'a' : undefined)
        expect(result.next).toEqual({ $pathname: '/home', locale: 'fr' })
    })

    test.each([
        {
            name: 'Unicode, lookbehind, lookahead and captures',
            path: '/日本語/😀',
            config: { pattern: '(?<=/)(日本語)(?=/)', replacePattern: '(?<=/)(日本語)(?=/)', replaceValue: '$1-$&' },
            expected: { $pathname: '/日本語-日本語/😀', locale: '日本語' },
        },
        {
            name: 'dollar replacement tokens and named groups',
            path: '/en/home',
            config: {
                replacePattern: '^/(?<language>[a-z]{2})',
                replaceValue: "$$:$&:$1:$<language>:$`:$'",
                replaceKey: 'result',
            },
            expected: { $pathname: '/en/home', locale: 'en', result: '$:/en:en:en::/home/home' },
        },
        {
            name: 'pathname capture is written before replacement',
            path: '/en/home',
            config: { property: '$pathname', replacePattern: '^en$', replaceValue: 'fr', replaceKey: 'result' },
            expected: { $pathname: 'en', result: 'fr' },
        },
        {
            name: 'unmatched optional capture',
            path: '/en',
            config: { pattern: '^/(en)(/)?', matchGroup: '2', replacePattern: '' },
            expected: { $pathname: '/en', locale: undefined },
        },
        {
            name: 'no match does not compile replacement',
            path: '/english',
            config: { replacePattern: '[' },
            expected: { $pathname: '/english' },
        },
        {
            name: 'pattern source remains data',
            path: '/en',
            config: { pattern: "'; throw new Error('executed'); //", replacePattern: '' },
            expected: { $pathname: '/en' },
        },
    ])('preserves native semantics: $name', ({ path, config, expected }) => {
        const event = makeEvent(path)
        expect(
            processEvent(event, { config: { ...globalConfig, ...config } } as unknown as LegacyTransformationPluginMeta)
        ).toBe(event)
        expect(event.properties).toEqual(expected)
    })

    test.each([undefined, null, 42, {}, []])('ignores non-string pathname %p without compiling patterns', (path) => {
        const event = makeEvent(path as unknown as string)
        expect(
            processEvent(event, {
                config: { ...globalConfig, pattern: '[' },
            } as unknown as LegacyTransformationPluginMeta)
        ).toBe(event)
        expect(event.properties).toEqual({ $pathname: path })
    })

    test.each(['pattern', 'replacePattern'])('propagates invalid %s and preserves prior mutations', (key) => {
        const event = makeEvent('/en/home')
        expect(() =>
            processEvent(event, { config: { ...globalConfig, [key]: '[' } } as LegacyTransformationPluginMeta)
        ).toThrow(SyntaxError)
        expect(event.properties).toEqual(
            key === 'pattern' ? { $pathname: '/en/home' } : { $pathname: '/en/home', locale: 'en' }
        )
    })

    test.each([
        ['^en', TypeError],
        ['[', SyntaxError],
    ])('preserves error order after overwriting pathname with an absent capture: %s', (replacePattern, error) => {
        const event = makeEvent('/en/home')
        expect(() =>
            processEvent(event, {
                config: { ...globalConfig, property: '$pathname', matchGroup: '5', replacePattern },
            } as unknown as LegacyTransformationPluginMeta)
        ).toThrow(error)
        expect(event.properties).toEqual({ $pathname: undefined })
    })
})

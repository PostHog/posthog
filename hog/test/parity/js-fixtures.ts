import { join } from 'node:path'

import { readTree } from './fixtures'

// JavaScript bundles and maps for the parity scenarios. Each case sits in its own folder, because
// posthog-cli walks folders in file-system order, and only cases with one bundle per folder give
// the same result on every machine.

const map = (fields: Record<string, unknown> = {}): string =>
    JSON.stringify({ version: 3, sources: ['src/a.ts'], names: [], mappings: 'AAAA', ...fields })

const ref = (name: string): string => `\n//# sourceMappingURL=${name}`

const DEBUG_ID = '11111111-2222-4333-8444-555555555555'

// Edge cases from the posthog-cli source: line endings, map lookup, map field types and numbers.
export const EDGE_CASES: Record<string, string | Uint8Array> = {
    'nonl/a.js': `a();\nb();${ref('a.js.map')}`,
    'nonl/a.js.map': map({ mappings: 'AAAA,EAAE;AACA;AACA;AACA', sourcesContent: ['x'] }),
    'crlf/a.js': 'a();\r\nb();\r\n//# sourceMappingURL=a.js.map\r\n',
    'crlf/a.js.map': map({ mappings: 'AAAA;AACA' }),
    'bom/a.js': `\uFEFFa();${ref('a.js.map')}\n`,
    'bom/a.js.map': map({ mappings: 'CAAA' }),
    'sibling/a.js': 'a();\n',
    'sibling/a.js.map': map(),
    'encoded/sub/a.js': `a();${ref('../maps/my%20map.js.map')}\n`,
    'encoded/maps/my map.js.map': map({ file: 'a.js' }),
    'inline/a.js': `a();${ref(`data:application/json;base64,${Buffer.from(map()).toString('base64')}`)}\n`,
    'nomap/a.js': 'a();\n',
    'mjs/a.mjs': `a();${ref('a.mjs.map')}\n`,
    'mjs/a.mjs.map': map(),
    'cjs/a.cjs': 'a();\n',
    'cjs/a.cjs.map': map(),
    'jsx/a.jsx': 'a();\n',
    'jsx/a.jsx.map': map(),
    'dotfile/.js': 'a();\n',
    'dotfile/.js.map': map(),
    'legacy/a.js': 'a();\n//@ sourceMappingURL=a.js.map\n',
    'legacy/a.js.map': JSON.stringify({
        version: 3,
        sources: ['a'],
        names: [],
        mappings: 'AAAA',
        chunkId: 'aaaaaaaa-0000-4000-8000-000000000000',
    }),
    'debugid/a.js': `a();\n//# debugId=${DEBUG_ID}${ref('a.js.map')}\n`,
    'debugid/a.js.map': map({ debugId: DEBUG_ID.toUpperCase() }),
    'debugid-simple/a.js': 'a();\n//# debugId=1111111122224333844455555555555F\n//# sourceMappingURL=a.js.map\n',
    'debugid-simple/a.js.map': map(),
    'debugid-malformed-source/a.js': `a();\n//# debugId=not-a-uuid${ref('a.js.map')}\n`,
    'debugid-malformed-source/a.js.map': map(),
    'index-map/a.js': `a();\nb();${ref('a.js.map')}\n`,
    'index-map/a.js.map': JSON.stringify({
        version: 3,
        file: 'a.js',
        sources: [],
        x_custom: 1,
        sections: [
            {
                offset: { line: 0, column: 0 },
                map: {
                    version: 3,
                    sources: ['one.ts'],
                    sourceRoot: 'webpack://',
                    names: ['n'],
                    mappings: 'AAAAA',
                    sourcesContent: ['one'],
                },
            },
            {
                offset: { line: 1, column: 2 },
                map: { version: 3, sources: ['two.ts', 'one.ts'], names: ['n'], mappings: 'AAAAA,CCAA' },
            },
        ],
    }),
    // Written by hand: floats, big numbers, escapes and key order JSON.stringify would change.
    'fields/a.js': `abc();${ref('a.js.map')}\n`,
    'fields/a.js.map':
        '{"version":3,"sourceRoot":"/root/","sources":[null,"b.ts"],"names":[1,null,"x",2.5],"mappings":"AAAAA,CCAAC,CAAAC","x_google_ignoreList":[1],"ignoreList":[1,1,0],"x_float":1.0,"x_big":1e21,"x_neg0":-0.0,"x_small":1e-7,"x_huge":18446744073709551615,"x_neg":-9223372036854775808,"x_unicode":"\\u00e9\\u2028/\\/\\u0001","file":42,"sourcesContent":[null,null,"extra"]}',
    'empty-small/a.js': `a();${ref('a.js.map')}\n`,
    'empty-small/a.js.map': JSON.stringify({ version: 3, sources: [], names: [], mappings: '' }),
    'empty-large/a.js': `${'a();'.repeat(600)}${ref('a.js.map')}\n`,
    'empty-large/a.js.map': JSON.stringify({ version: 3, sources: [], names: [], mappings: '' }),
    'xssi/a.js': `a();${ref('a.js.map')}\n`,
    'xssi/a.js.map': `)]}'\n${map()}`,
    'latin1/a.js': Buffer.from(`a('\xe9');${ref('a.js.map')}\n`, 'latin1'),
    'latin1/a.js.map': map(),
    'empty-source/a.js': '',
    'empty-source/a.js.map': map({ mappings: '' }),
    'multibyte/a.js': `var s='é日😀';f();${ref('a.js.map')}\n`,
    'multibyte/a.js.map': map({ mappings: 'AAAA,UAAU,QAAQ' }),
    'facebook/a.js': `a();${ref('a.js.map')}\n`,
    'facebook/a.js.map': map({ x_facebook_sources: [[{ names: ['<global>'], mappings: 'AAA' }]] }),
    'file-paths/a.js': `import("./one-BrAf3own.js");x.js.map;${ref('a.js.map')}\n`,
    'file-paths/a.js.map': map({ file: 'https://cdn.example.com/a/b-X_1.mjs' }),
    'reference-not-last/a.js': `a();${ref('a.js.map')}\nb();\n`,
    'reference-not-last/a.js.map': map({ mappings: 'AAAA;AACA' }),
}

// A map whose debugId is not a UUID fails the whole posthog-cli run before any file is written.
export const MALFORMED_MAP_DEBUG_ID: Record<string, string> = {
    'ok/a.js': `a();${ref('a.js.map')}\n`,
    'ok/a.js.map': map(),
    'bad/a.js': `a();${ref('a.js.map')}\n`,
    'bad/a.js.map': map({ debugId: 'not-a-uuid' }),
}

export const PUBLIC_PATH: Record<string, string> = {
    'static/js/a.js': `a();${ref('/static/js/a.js.map')}\n`,
    'static/js/a.js.map': map(),
}

export const STYLESHEETS: Record<string, string> = {
    'dist/a.js': `a();${ref('a.js.map')}\n`,
    'dist/a.js.map': map(),
    'dist/site.css': '.a{color:red}\n/*# sourceMappingURL=site.css.map */\n',
    'dist/site.css.map': map({ sources: ['site.scss'] }),
    'dist/inline.css': '.b{} /*# sourceMappingURL=inline.css.map */ .c{}\n',
    'dist/inline.css.map': map({ sources: ['inline.scss'] }),
}

// Stylesheets whose reference doesn't name the map directly: a CDN URL that --public-path-prefix
// strips, and a stale name that falls back to the map next to the stylesheet.
export const STYLESHEET_LOOKUP: Record<string, string> = {
    'dist/a.js': `a();${ref('a.js.map')}\n`,
    'dist/a.js.map': map(),
    'dist/cdn.css': '.a{}\n/*# sourceMappingURL=https://cdn.example.com/assets/cdn.css.map */\n',
    'dist/cdn.css.map': map({ sources: ['cdn.scss'] }),
    'dist/stale.css': '.b{}\n/*# sourceMappingURL=stale.0f3a.css.map */\n',
    'dist/stale.css.map': map({ sources: ['stale.scss'] }),
}

// Real bundler output, built from the small app in bundles/README.md.
export const bundles = (): Record<string, Uint8Array> => readTree(join(import.meta.dir, 'bundles'))

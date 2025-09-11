import { Hub } from '../../src/types'
import { closeHub, createHub } from '../../src/utils/db/hub'
import { code } from '../../src/utils/utils'
import { transformCode } from '../../src/worker/vm/transforms'
import { resetTestDatabase } from '../helpers/sql'

jest.mock('../../src/utils/logger')

const EMPTY_IMPORTS = {}

describe('transforms', () => {
    let hub: Hub

    beforeEach(async () => {
        hub = await createHub()
        await resetTestDatabase(`const processEvent = event => event`)
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    describe('transformCode', () => {
        it('secures awaits by wrapping promises in __asyncGuard', () => {
            const rawCode = code`
            async function x() {
              await console.log()
            }
        `

            const transformedCode = transformCode(rawCode, hub, EMPTY_IMPORTS, new Set())

            expect(transformedCode).toStrictEqual(code`
            "use strict";

            async function x() {
              await __asyncGuard(console.log(), "await on line 2:2");
            }
        `)
        })

        it('attaches caller information to awaits', () => {
            const rawCode = code`
            async function x() {
              await anotherAsyncFunction('arg1', 'arg2')
            }
        `

            const transformedCode = transformCode(rawCode, hub, EMPTY_IMPORTS, new Set())

            expect(transformedCode).toStrictEqual(code`
            "use strict";

            async function x() {
              await __asyncGuard(anotherAsyncFunction('arg1', 'arg2'), "await on line 2:2");
            }
        `)
        })

        it('attaches caller information to awaits for anonymous functions', () => {
            const rawCode = code`
            async function x() {
              await (async () => {console.log()})
            }
        `

            const transformedCode = transformCode(rawCode, hub, EMPTY_IMPORTS, new Set())

            expect(transformedCode).toStrictEqual(code`
            "use strict";

            async function x() {
              await __asyncGuard(async () => {
                console.log();
              }, "await on line 2:2");
            }
        `)
        })

        it('secures then calls by wrapping promises in __asyncGuard', () => {
            const rawCode = code`
            async function x() {}
            x.then(() => null)
        `

            const transformedCode = transformCode(rawCode, hub, EMPTY_IMPORTS, new Set())

            expect(transformedCode).toStrictEqual(code`
            "use strict";

            async function x() {}
            __asyncGuard(x, "Promise.then on line 2:0").then(() => null);
        `)
        })

        it('secures block for loops with timeouts', () => {
            const rawCode = code`
            for (let i = 0; i < i + 1; i++) {
                console.log(i)
            }
        `

            const transformedCode = transformCode(rawCode, hub, EMPTY_IMPORTS, new Set())

            expect(transformedCode).toStrictEqual(code`
            "use strict";

            const _LP = Date.now();
            for (let i = 0; i < i + 1; i++) {
              if (Date.now() - _LP > 30000) throw new Error("Script execution timed out after looping for 30 seconds on line 1:0");
              console.log(i);
            }
        `)
        })

        it('secures inline for loops with timeouts', () => {
            const rawCode = code`
            for (let i = 0; i < i + 1; i++) console.log(i)
        `

            const transformedCode = transformCode(rawCode, hub, EMPTY_IMPORTS, new Set())

            expect(transformedCode).toStrictEqual(code`
            "use strict";

            const _LP = Date.now();
            for (let i = 0; i < i + 1; i++) {
              if (Date.now() - _LP > 30000) throw new Error("Script execution timed out after looping for 30 seconds on line 1:0");
              console.log(i);
            }
        `)
        })

        it('secures block for loops with timeouts avoiding _LP collision', () => {
            const rawCode = code`
            const _LP = 0

            for (let i = 0; i < i + 1; i++) {
                console.log(i)
            }
        `

            const transformedCode = transformCode(rawCode, hub, EMPTY_IMPORTS, new Set())

            expect(transformedCode).toStrictEqual(code`
            "use strict";

            const _LP = 0;
            const _LP2 = Date.now();
            for (let i = 0; i < i + 1; i++) {
              if (Date.now() - _LP2 > 30000) throw new Error("Script execution timed out after looping for 30 seconds on line 3:0");
              console.log(i);
            }
        `)
        })

        it('transforms TypeScript to plain JavaScript', () => {
            const rawCode = code`
            interface Y {
              a: int
              b: string
            }

            function k({ a, b }: Y): string {
                return \`a * 10 is {a * 10}, while b is just {b}\`
            }

            let a: int = 2
            console.log(k({ a, b: 'tomato' }))
        `

            const transformedCode = transformCode(rawCode, hub, EMPTY_IMPORTS, new Set())

            expect(transformedCode).toStrictEqual(code`
            "use strict";

            function k({
              a,
              b
            }) {
              return \`a * 10 is {a * 10}, while b is just {b}\`;
            }
            let a = 2;
            console.log(k({
              a,
              b: 'tomato'
            }));
        `)
        })

        it('replaces imports', () => {
            const rawCode = code`
            import { bla, bla2, bla3 as bla4 } from 'node-fetch'
            import fetch1 from 'node-fetch'
            import * as fetch2 from 'node-fetch'
            console.log(bla, bla2, bla4, fetch1, fetch2);
        `
            const usedImports = new Set<string>()
            const transformedCode = transformCode(rawCode, hub, { 'node-fetch': { bla: () => true } }, usedImports)
            expect(usedImports).toEqual(new Set(['node-fetch']))

            expect(transformedCode).toStrictEqual(code`
            "use strict";

            const bla = __pluginHostImports["node-fetch"]["bla"],
              bla2 = __pluginHostImports["node-fetch"]["bla2"],
              bla4 = __pluginHostImports["node-fetch"]["bla3"];
            const fetch1 = __pluginHostImports["node-fetch"];
            const fetch2 = __pluginHostImports["node-fetch"];
            console.log(bla, bla2, bla4, fetch1, fetch2);
        `)
        })

        it('only replaces provided imports', () => {
            const rawCode = code`
            import { kea } from 'kea'
            console.log(kea)
        `

            expect(() => {
                transformCode(rawCode, hub, { 'node-fetch': { default: () => true } }, new Set())
            }).toThrow("/index.ts: Cannot import 'kea'! This package is not provided by PostHog in plugins.")
        })

        it('replaces requires', () => {
            const rawCode = code`
            const fetch = require('node-fetch')
            const { BigQuery } = require('@google-cloud/bigquery')
            console.log(fetch, BigQuery);
        `

            const usedImports = new Set<string>()
            const transformedCode = transformCode(
                rawCode,
                hub,
                {
                    'node-fetch': { bla: () => true },
                    '@google-cloud/bigquery': { BigQuery: () => true },
                },
                usedImports
            )
            expect(usedImports).toEqual(new Set(['node-fetch', '@google-cloud/bigquery']))

            expect(transformedCode).toStrictEqual(code`
            "use strict";

            const fetch = __pluginHostImports["node-fetch"];
            const {
              BigQuery
            } = __pluginHostImports["@google-cloud/bigquery"];
            console.log(fetch, BigQuery);
        `)
        })

        it('only replaces provided requires', () => {
            const rawCode = code`
            const { kea } = require('kea')
            console.log(kea)
        `

            expect(() => {
                transformCode(rawCode, hub, { 'node-fetch': { default: () => true } }, new Set())
            }).toThrow("/index.ts: Cannot import 'kea'! This package is not provided by PostHog in plugins.")
        })
    })
})

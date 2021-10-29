import { Hub } from '../src/types'
import { createHub } from '../src/utils/db/hub'
import { code } from '../src/utils/utils'
import { transformCode } from '../src/worker/vm/transforms'
import { resetTestDatabase } from './helpers/sql'

let hub: Hub
let closeHub: () => Promise<void>

beforeEach(async () => {
    ;[hub, closeHub] = await createHub()
    await resetTestDatabase(`const processEvent = event => event`)
})

afterEach(async () => {
    await closeHub()
})

describe('transformCode', () => {
    it('secures awaits by wrapping promises in __asyncGuard', () => {
        const rawCode = code`
            async function x() {
              await console.log()
            }
        `

        const transformedCode = transformCode(rawCode, hub)

        expect(transformedCode).toStrictEqual(code`
            "use strict";

            async function x() {
              await __asyncGuard(console.log(), console.log);
            }
        `)
    })

    it('attaches caller information to awaits', () => {
        const rawCode = code`
            async function x() {
              await anotherAsyncFunction('arg1', 'arg2')
            }
        `

        const transformedCode = transformCode(rawCode, hub)

        expect(transformedCode).toStrictEqual(code`
            "use strict";

            async function x() {
              await __asyncGuard(anotherAsyncFunction('arg1', 'arg2'), anotherAsyncFunction);
            }
        `)
    })

    it('attaches caller information to awaits for anonymous functions', () => {
        const rawCode = code`
            async function x() {
              await (async () => {console.log()})
            }
        `

        const transformedCode = transformCode(rawCode, hub)

        expect(transformedCode).toStrictEqual(code`
            "use strict";

            async function x() {
              await __asyncGuard(async () => {
                console.log();
              }, async () => {
                console.log();
              });
            }
        `)
    })

    it('secures then calls by wrapping promises in __asyncGuard', () => {
        const rawCode = code`
            async function x() {}
            x.then(() => null)
        `

        const transformedCode = transformCode(rawCode, hub)

        expect(transformedCode).toStrictEqual(code`
            "use strict";

            async function x() {}

            __asyncGuard(x).then(() => null);
        `)
    })

    it('secures block for loops with timeouts', () => {
        const rawCode = code`
            for (let i = 0; i < i + 1; i++) {
                console.log(i)
            }
        `

        const transformedCode = transformCode(rawCode, hub)

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

        const transformedCode = transformCode(rawCode, hub)

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

        const transformedCode = transformCode(rawCode, hub)

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

        const transformedCode = transformCode(rawCode, hub)

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

        const transformedCode = transformCode(rawCode, hub, { 'node-fetch': { bla: () => true } })

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
            transformCode(rawCode, hub, { 'node-fetch': { default: () => true } })
        }).toThrow("/index.ts: Cannot import 'kea'! This package is not provided by PostHog in plugins.")
    })

    it('replaces requires', () => {
        const rawCode = code`
            const fetch = require('node-fetch')
            const { BigQuery } = require('@google-cloud/bigquery')
            console.log(fetch, BigQuery);
        `

        const transformedCode = transformCode(rawCode, hub, {
            'node-fetch': { bla: () => true },
            '@google-cloud/bigquery': { BigQuery: () => true },
        })

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
            transformCode(rawCode, hub, { 'node-fetch': { default: () => true } })
        }).toThrow("/index.ts: Cannot import 'kea'! This package is not provided by PostHog in plugins.")
    })
})

import assert from 'node:assert/strict'
import { test } from 'node:test'
import { runInNewContext } from 'node:vm'

import { compileFragment } from './sketchpad.mjs'

test('preserves JSX, types, shared imports, async initialization, and separate module state', async () => {
    const { code, imports } = compileFragment(String.raw`
        import type { ReactNode } from "react";
        import React from "react";
        export { useState } from "react";
        export * as ReactExports from "react";
        const label: string = await Promise.resolve("ready");
        let count = 0;
        export default () => <div title="\u{1F680}">\u263A{label}{++count}</div>;
    `)
    assert.deepEqual(imports.sort(), ['react', 'react/jsx-runtime'])
    const run = () =>
        runInNewContext(`(async function(require, exports) { ${code}; return exports; })(require, {})`, {
            require: () => ({ jsx: (tag, props) => props, jsxs: (tag, props) => props }),
        })
    const first = await run()
    const second = await run()
    assert.equal(first.default().title, '🚀')
    assert.equal(JSON.stringify(first.default().children), JSON.stringify(['☺', 'ready', 2]))
    assert.equal(JSON.stringify(second.default().children), JSON.stringify(['☺', 'ready', 1]))
})

test('rejects unsupported imports and runtime loading', () => {
    for (const source of [
        'import "node:fs";',
        'export * from "https://example.com/code.js";',
        'import("react");',
        'require("react");',
        'eval("1");',
        'new Function("return 1");',
        'const url = import.meta.url;',
    ]) {
        assert.throws(() => compileFragment(source))
    }
})

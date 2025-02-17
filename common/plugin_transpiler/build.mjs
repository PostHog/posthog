#!/usr/bin/env node
import * as esbuild from 'esbuild'
;(async function build() {
    let result = await esbuild.build({
        entryPoints: ['src/index.ts'],
        bundle: true,
        outdir: 'dist',
    })
    if (!result.errors.length) {
        // eslint-disable-next-line no-console
        console.log('Build succeeded')
    }
})()

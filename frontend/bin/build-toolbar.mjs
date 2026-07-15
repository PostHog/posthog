#!/usr/bin/env node
/**
 * Builds the toolbar bundle for use alongside the Vite dev server.
 *
 * When using Vite for development, the main app is served via Vite's dev server with HMR.
 * The toolbar is a separate bundle loaded via /static/toolbar.js (proxied to Django), so it
 * isn't part of the Vite graph. This script builds and watches it, rebuilding when
 * toolbar-related files change.
 */
import * as path from 'path'
import { fileURLToPath } from 'url'

import { buildInParallel } from '@posthog/esbuilder'

import { finalizeToolbarBuild, getToolbarAppBuildConfig } from '../toolbar-config.mjs'

const __dirname = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')

const common = {
    absWorkingDir: __dirname,
    bundle: true,
}

await buildInParallel(
    [
        {
            ...getToolbarAppBuildConfig(__dirname),
            ...common,
        },
    ],
    {
        async onBuildComplete(config, buildResponse) {
            await finalizeToolbarBuild(__dirname, buildResponse)
        },
    }
)

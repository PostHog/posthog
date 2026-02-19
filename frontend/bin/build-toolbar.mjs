#!/usr/bin/env node
/**
 * Builds the toolbar bundle for use alongside Vite dev server.
 *
 * When using Vite for development, the main app is served via Vite's dev server with HMR.
 * However, the toolbar is loaded as a separate IIFE bundle via /static/toolbar.js,
 * which is proxied to Django. This script watches and rebuilds the toolbar when
 * toolbar-related files change.
 */
import * as path from 'path'
import { fileURLToPath } from 'url'

import { buildInParallel } from '@posthog/esbuilder'

import { getToolbarBuildConfig } from '../toolbar-config.mjs'

const __dirname = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')

const common = {
    absWorkingDir: __dirname,
    bundle: true,
}

await buildInParallel(
    [
        {
            ...getToolbarBuildConfig(__dirname),
            ...common,
        },
    ],
    {}
)

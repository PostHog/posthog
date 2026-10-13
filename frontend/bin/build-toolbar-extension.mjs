#!/usr/bin/env node
/**
 * Builds the toolbar browser extension into dist/toolbar-extension/<browser>/.
 * Pass --dev to watch and rebuild.
 */
import * as path from 'path'
import { fileURLToPath } from 'url'

import { buildInParallel } from '@posthog/esbuilder'

import {
    finalizeToolbarExtensionBuild,
    getToolbarExtensionBuildConfig,
    getToolbarExtensionContentScriptBuildConfig,
} from '../toolbar-config.mjs'

const __dirname = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')

await buildInParallel(
    [
        {
            ...getToolbarExtensionBuildConfig(__dirname),
            absWorkingDir: __dirname,
            bundle: true,
        },
        {
            ...getToolbarExtensionContentScriptBuildConfig(__dirname),
            absWorkingDir: __dirname,
            bundle: true,
        },
    ],
    {
        onBuildComplete(config, buildResponse) {
            if (buildResponse) {
                finalizeToolbarExtensionBuild(__dirname)
            }
        },
    }
)

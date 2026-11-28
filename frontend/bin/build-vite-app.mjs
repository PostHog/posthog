#!/usr/bin/env node
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { finishViteAppBuild } from './viteAppBuild.mjs'

finishViteAppBuild(path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..'))

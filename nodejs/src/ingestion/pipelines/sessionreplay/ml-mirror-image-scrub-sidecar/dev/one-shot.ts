/* eslint-disable no-console -- CLI output script: console output is the whole point */
/** Scrub one file under whatever env this process was started with, and write the result.
 *
 *   SCRUB_MAX_PIXELS=1000000 tsx dev/one-shot.ts corpus/shot.png out/a.png
 */
import { readFile, writeFile } from 'node:fs/promises'

import { advancedScrub, loadModels } from '../src/scrub.ts'

const [input, output] = process.argv.slice(2)
const models = await loadModels()
const { out, t } = await advancedScrub(await readFile(input), models, 'dbnet')
await writeFile(output, out)
console.log(`${output}: text=${t.textBoxes} faces=${t.faces} codes=${t.codes} ${t.totalMs.toFixed(0)}ms`)

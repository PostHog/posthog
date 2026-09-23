import { writeFileSync } from 'fs'
import { join } from 'path'

import {
    FILTER_GLOBALS_RELATIVE_PATH,
    describeFilterRuntime,
    renderFilterGlobalsFile,
} from '../src/cdp/utils/filter-runtime'

const target = join(__dirname, '..', '..', FILTER_GLOBALS_RELATIVE_PATH)
writeFileSync(target, renderFilterGlobalsFile(describeFilterRuntime()))
console.info(`wrote ${target}`)

import { exec } from 'child_process'
import { createHash } from 'crypto'
import { mkdir, readFile, writeFile } from 'fs/promises'
import { tmpdir } from 'os'
import path from 'path'

import { parseJSON } from '~/common/utils/json-parse'
import { UUIDT } from '~/common/utils/utils'

import { HogBytecode } from '../types'
import { Semaphore } from '../utils/sempahore'

const ROOT_DIR = path.join(__dirname, '..', '..', '..', '..')
const CACHE_DIR = path.join(ROOT_DIR, 'nodejs', 'tests', 'fixtures', 'hog-bytecode')
const CACHE_REWRITE = process.env.HOG_BYTECODE_CACHE_REWRITE === '1'
const CACHE_REQUIRED = process.env.HOG_BYTECODE_CACHE_REQUIRED === 'true'

const cache = new Map<string, HogBytecode>()
const CONCURRENT_WORKERS = 10

const semaphore = new Semaphore(CONCURRENT_WORKERS)

function cacheFile(hog: string): string {
    return path.join(CACHE_DIR, `${createHash('sha256').update(hog).digest('hex')}.json`)
}

export async function compileHog(hog: string): Promise<HogBytecode> {
    return semaphore.run(async () => {
        const cached = cache.get(hog)
        if (cached) {
            return cached
        }

        const file = cacheFile(hog)
        let cacheMiss = false
        if (!CACHE_REWRITE) {
            try {
                const bytecode = parseJSON(await readFile(file, 'utf-8')) as HogBytecode
                cache.set(hog, bytecode)
                return bytecode
            } catch (error) {
                if ((error as NodeJS.ErrnoException).code !== 'ENOENT') {
                    throw error
                }
                cacheMiss = true
            }
        }

        if (CACHE_REQUIRED) {
            throw new Error(
                `Missing compiled Hog bytecode fixture: ${file}. Run this test file locally and commit the generated fixture.`
            )
        }

        // We invoke the ./bin/hog from the root of the directory like bin/hoge <file.hog> [output.hoge]
        // We need to write and read from a temp file
        const uuid = new UUIDT().toString()
        const tempFile = path.join(tmpdir(), `hog-${uuid}.hog`)
        await writeFile(tempFile, hog)

        const outputFile = path.join(tmpdir(), `hog-${uuid}.hoge`)
        try {
            await new Promise((resolve, reject) => {
                exec(
                    `cd ${ROOT_DIR} && ./bin/hoge ${tempFile} ${outputFile}`,
                    {
                        env: {
                            ...process.env,
                            TEST: 'true',
                        },
                    },
                    (error, stdout) => (error ? reject(error) : resolve(stdout))
                )
            })
        } catch (error) {
            console.error('Failed to compile hog:', hog)
            throw error
        }

        const output = parseJSON(await readFile(outputFile, 'utf-8'))

        cache.set(hog, output)
        if (CACHE_REWRITE || cacheMiss) {
            await mkdir(CACHE_DIR, { recursive: true })
            await writeFile(file, JSON.stringify(output) + '\n')
        }

        return output
    })
}

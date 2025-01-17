import { exec } from 'child_process'
import { mkdirSync, readFileSync } from 'fs'
import { readFile, writeFile } from 'fs/promises'
import { tmpdir } from 'os'
import path from 'path'

import { UUIDT } from '../../utils/utils'
import { HogBytecode } from '../types'

const ROOT_DIR = path.join(__dirname, '..', '..', '..', '..')
const CACHE_FILE = path.join(__dirname, '.tmp/cache.json')

let CACHE: Record<string, HogBytecode> | null = null

export async function compileHog(hog: string): Promise<HogBytecode> {
    if (CACHE === null) {
        mkdirSync(path.dirname(CACHE_FILE), { recursive: true })

        // Load from the tmp dir if it exists, otherwise new object
        try {
            CACHE = JSON.parse(readFileSync(CACHE_FILE, 'utf-8'))
        } catch (error) {
            CACHE = {}
        }
    }
    CACHE = CACHE ?? {}

    if (CACHE[hog]) {
        return CACHE[hog]
    }

    // We invoke the ./bin/hog from the root of the directory like bin/hoge <file.hog> [output.hoge]
    // We need to write and read from a temp file
    const uuid = new UUIDT().toString()
    const tempFile = path.join(tmpdir(), `hog-${uuid}.hog`)
    await writeFile(tempFile, hog)

    const outputFile = path.join(tmpdir(), `hog-${uuid}.hoge`)
    try {
        await new Promise((resolve, reject) => {
            exec(`cd ${ROOT_DIR} && ./bin/hoge ${tempFile} ${outputFile}`, (error, stdout) =>
                error ? reject(error) : resolve(stdout)
            )
        })
    } catch (error) {
        console.error('Failed to compile hog:', hog)
        throw error
    }

    const output = JSON.parse(await readFile(outputFile, 'utf-8'))

    CACHE[hog] = output

    await writeFile(CACHE_FILE, JSON.stringify(CACHE, null, 2))

    return output
}

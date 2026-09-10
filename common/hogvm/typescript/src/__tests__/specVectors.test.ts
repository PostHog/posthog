import * as fs from 'fs'
import * as path from 'path'

import { execSync } from '../execute'

const VECTORS_DIR = path.join(__dirname, '..', '..', '..', 'spec', 'vectors')

interface SpecVector {
    name: string
    fn: string
    implementations: string[]
    bytecode: any[]
    expect: { error?: string; result?: any }
}

describe('spec vectors', () => {
    const cases: SpecVector[] = fs
        .readdirSync(VECTORS_DIR)
        .filter((file) => file.endsWith('.json'))
        .sort()
        .flatMap((file) => JSON.parse(fs.readFileSync(path.join(VECTORS_DIR, file), 'utf-8')).cases)
        .filter((vector: SpecVector) => vector.implementations.includes('typescript'))

    test.each(cases.map((vector) => [vector.name, vector] as const))('%s', (_name, vector) => {
        if (vector.expect.error !== undefined) {
            let message: string | null = null
            try {
                execSync(vector.bytecode)
            } catch (e: any) {
                message = e.message
            }
            expect(message).toBe(vector.expect.error)
        } else {
            expect(execSync(vector.bytecode)).toEqual(vector.expect.result)
        }
    })
})

import { existsSync, readFileSync } from 'fs'
import path from 'path'
import { z } from 'zod'

import { parseJSON } from '~/common/utils/json-parse'

export const SAVED_RUN_FILE = 'scorecard.json'

export const SavedRun = z.object({ host: z.string().optional(), event: z.record(z.string(), z.unknown()) })

export type SavedRun = z.infer<typeof SavedRun>

export const savedRunPathOf = (runDir: string): string => path.join(runDir, SAVED_RUN_FILE)

export function readSavedRun(runDir: string): { run: SavedRun } | { problem: string } {
    const saved = savedRunPathOf(runDir)
    if (!existsSync(saved)) {
        return { problem: `no scorecard at ${saved}` }
    }
    const parsed = SavedRun.safeParse(parseJSON(readFileSync(saved, 'utf8')))
    return parsed.success
        ? { run: parsed.data }
        : { problem: `${saved} holds no scorecard event: ${parsed.error.issues[0].message}` }
}

import { relative } from 'node:path'
import { parse } from 'yaml'

import { absolutePath } from '@/core/paths'
import type { Runtime } from '@/core/runtime'

import { EndpointFile } from './model'

export interface LocalEndpoint {
    path: string
    file: EndpointFile
}

export interface FileProblem {
    path: string
    message: string
}

const isYaml = (name: string): boolean => /\.ya?ml$/i.test(name)

// Reads the endpoint files in the given files, folders (not recursive) and glob patterns. A file
// that doesn't parse is a problem to report, not a reason to stop the others.
export async function readEndpointFiles(
    runtime: Runtime,
    paths: readonly string[]
): Promise<{ endpoints: LocalEndpoint[]; problems: FileProblem[] }> {
    const cwd = runtime.cwd()
    const found: string[] = []
    const problems: FileProblem[] = []
    for (const path of paths) {
        const absolute = absolutePath(cwd, path)
        if (await runtime.isDirectory(absolute)) {
            const names = (await runtime.listFiles(absolute)).filter(isYaml)
            found.push(...names.map((name) => `${absolute.replace(/\/$/, '')}/${name}`))
        } else if (await runtime.exists(absolute)) {
            found.push(absolute)
        } else {
            const matches = await runtime.glob(path, cwd)
            if (matches.length === 0) {
                problems.push({ path, message: 'No such file or folder' })
            }
            found.push(...matches.map((match) => absolutePath(cwd, match)))
        }
    }

    const endpoints: LocalEndpoint[] = []
    for (const absolute of new Set(found)) {
        const path = relative(cwd, absolute) || absolute
        let raw: unknown
        try {
            raw = parse(await runtime.readFile(absolute))
        } catch (error) {
            problems.push({ path, message: `Not valid YAML: ${error instanceof Error ? error.message : error}` })
            continue
        }
        const parsed = EndpointFile.safeParse(raw)
        if (parsed.success) {
            endpoints.push({ path, file: parsed.data })
        } else {
            const [issue] = parsed.error.issues
            const where = issue?.path.length ? `${issue.path.join('.')}: ` : ''
            problems.push({ path, message: `${where}${issue?.message ?? 'not an endpoint file'}` })
        }
    }
    return { endpoints, problems }
}

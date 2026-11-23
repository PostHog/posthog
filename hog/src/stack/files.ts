import { isAbsolute, relative, resolve, sep } from 'node:path'

import { EXIT_USAGE, HogError } from '@/core/errors'
import { escapeControls } from '@/core/output'
import { isInside, realWritePath } from '@/core/paths'
import type { Runtime } from '@/core/runtime'

export interface GeneratedFile {
    path: string
    contents: string
}

export interface FileEdit extends GeneratedFile {
    target: string
    before?: string
}

export async function insideFolder(runtime: Runtime, folder: string, name: string, allowRoot = false): Promise<string> {
    const target = resolve(folder, name)
    const [base, resolved] = await Promise.all([realWritePath(runtime, folder), realWritePath(runtime, target)])
    const same = allowRoot && folder === target && base === resolved
    if (isAbsolute(name) || (!same && (!isInside(folder, target) || !isInside(base, resolved)))) {
        throw new HogError(
            'stack_path_outside',
            'A stack file points outside its folder.',
            'Choose a relative path inside the folder and check its links.',
            EXIT_USAGE
        )
    }
    return resolved
}

export async function fileEdits(
    runtime: Runtime,
    root: string,
    generated: GeneratedFile[],
    appendExports = false
): Promise<FileEdit[]> {
    const edits: FileEdit[] = []
    for (const file of generated) {
        const target = await insideFolder(runtime, root, file.path)
        const before = (await runtime.exists(target)) ? await runtime.readFile(target) : undefined
        let contents = file.contents
        if (appendExports && file.path === 'index.ts' && before !== undefined) {
            const existing = new Set(before.split(/\r?\n/).map((line) => line.trim()))
            const added = contents.split(/\r?\n/).filter((line) => line.trim() && !existing.has(line.trim()))
            contents = added.length ? `${before.trimEnd()}\n${added.join('\n')}\n` : before
        }
        if (contents !== before) {
            edits.push({ path: file.path, target, contents, before })
        }
    }
    return edits
}

export async function previewEdits(edits: FileEdit[]): Promise<string[]> {
    const { createTwoFilesPatch } = await import('diff')
    return edits.map(({ path, before, contents }) =>
        before === undefined
            ? `Create ${escapeControls(path)}`
            : createTwoFilesPatch(path, path, before, contents).split('\n').map(escapeControls).join('\n').trimEnd()
    )
}

export async function writeEdits(runtime: Runtime, edits: FileEdit[]): Promise<void> {
    const written: FileEdit[] = []
    try {
        for (const edit of edits) {
            if (edit.before === undefined) {
                if (!(await runtime.createFile(edit.target, edit.contents))) {
                    throw changedFile()
                }
            } else {
                if ((await runtime.readFile(edit.target)) !== edit.before) {
                    throw changedFile()
                }
                await runtime.replaceFile(edit.target, edit.contents)
            }
            written.push(edit)
        }
    } catch (error) {
        await undoEdits(runtime, written)
        if (error instanceof HogError) {
            throw error
        }
        throw new HogError(
            'stack_write_failed',
            'Could not write the stack files.',
            'Check the folder permissions and run the command again.'
        )
    }
}

function changedFile(): HogError {
    return new HogError(
        'stack_file_changed',
        'A file changed while hog was preparing to write it.',
        'Review the file and run the command again.'
    )
}

export async function undoEdits(runtime: Runtime, edits: FileEdit[]): Promise<void> {
    for (const { target, contents, before } of [...edits].reverse()) {
        if ((await runtime.readFile(target).catch(() => undefined)) !== contents) {
            continue
        }
        if (before === undefined) {
            await runtime.removeFile(target)
        } else {
            await runtime.replaceFile(target, before)
        }
    }
}

export function displayPath(root: string, path: string): string {
    return relative(root, path).split(sep).join('/')
}

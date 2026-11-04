import { mkdirSync, readdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, join, relative } from 'node:path'

// Fixture files written into a fresh folder per run, outside any git repository unless a scenario
// builds one, so neither CLI picks up the machine's own git or CI state.

export const SMALL_MAPPING = [
    '# compiler: R8',
    '# compiler_version: 8.2.47',
    'com.example.app.MainActivity -> com.example.app.MainActivity:',
    '    1:1:void <init>():12:12 -> <init>',
    '    1:4:void onCreate(android.os.Bundle):16:19 -> onCreate',
    'com.example.app.Model -> a.a:',
    '    java.lang.String name -> a',
    '    1:1:java.lang.String getName():8:8 -> a',
    '',
].join('\n')

export function mappingOfSize(size: number): string {
    const lines = ['com.example.app.Big -> a.b:']
    let index = 0
    let text = `${lines[0]}\n`
    while (text.length < size - 200) {
        text += `    ${index}:${index}:void method${index}(int):${index}:${index} -> m${index % 97}\n`
        index++
    }
    const padding = size - text.length - 3
    return `${text}# ${'x'.repeat(padding)}\n`
}

export function write(folder: string, files: Record<string, string | Uint8Array>): void {
    for (const [path, contents] of Object.entries(files)) {
        const full = join(folder, path)
        mkdirSync(dirname(full), { recursive: true })
        writeFileSync(full, contents)
    }
}

// A minimal repository on disk: what posthog-cli and hog read without running git.
export const GIT_REPO: Record<string, string> = {
    '.git/HEAD': 'ref: refs/heads/main\n',
    '.git/refs/heads/main': 'c0ffee00c0ffee00c0ffee00c0ffee00c0ffee00\n',
    '.git/config':
        '[core]\n\tbare = false\n[remote "origin"]\n\turl = https://x-access-token:secret@github.com/PostHog/example-app.git\n\tfetch = +refs/heads/*:refs/remotes/origin/*\n',
}

// Every file under a checked-in fixture folder except its README, keyed by relative path.
export function readTree(root: string, prefix = ''): Record<string, Uint8Array> {
    const files: Record<string, Uint8Array> = {}
    const visit = (folder: string): void => {
        for (const entry of readdirSync(folder, { withFileTypes: true })) {
            const path = join(folder, entry.name)
            if (entry.isDirectory()) {
                visit(path)
            } else if (entry.name !== 'README.md') {
                files[join(prefix, relative(root, path))] = readFileSync(path)
            }
        }
    }
    visit(root)
    return files
}

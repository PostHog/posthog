import { describe, expect, test } from 'bun:test'

import { resolveMode, type OutputFormat, type Terminal } from './agent'

const TERMINALS: Record<string, Terminal> = {
    tty: { isTTY: true, hasColors: true, columns: 80 },
    pipe: { isTTY: false, hasColors: false, columns: undefined },
    dumb: { isTTY: true, hasColors: false, columns: 80 },
}

describe('resolveMode', () => {
    test.each([
        ['a person at a terminal gets text with color', {}, 'tty', undefined, undefined, 'text', true],
        ['a pipe gets json', {}, 'pipe', undefined, undefined, 'json', false],
        ['Claude Code gets json without color', { CLAUDECODE: '1' }, 'tty', undefined, 'claude-code', 'json', false],
        [
            'Codex is detected by its sandbox variable',
            { CODEX_SANDBOX: 'seatbelt' },
            'tty',
            undefined,
            'codex',
            'json',
            false,
        ],
        ['AI_AGENT names the agent', { AI_AGENT: 'v0' }, 'tty', undefined, 'v0', 'json', false],
        [
            'HOG_AGENT=0 overrides detection',
            { CLAUDECODE: '1', HOG_AGENT: '0' },
            'tty',
            undefined,
            undefined,
            'text',
            true,
        ],
        ['HOG_AGENT=1 forces agent mode', { HOG_AGENT: '1' }, 'tty', undefined, 'unknown', 'json', false],
        [
            "Cursor's own terminal is not an agent",
            { CURSOR_TRACE_ID: 'abc' },
            'tty',
            undefined,
            undefined,
            'text',
            true,
        ],
        ['--output json wins at a terminal', {}, 'tty', 'json', undefined, 'json', false],
        [
            '--output text for an agent stays uncolored',
            { CLAUDECODE: '1' },
            'tty',
            'text',
            'claude-code',
            'text',
            false,
        ],
        ['NO_COLOR turns color off', { NO_COLOR: '1' }, 'tty', undefined, undefined, 'text', false],
        [
            'a terminal without color support, like TERM=dumb, gets plain text',
            {},
            'dumb',
            undefined,
            undefined,
            'text',
            false,
        ],
    ] as const)('%s', (_name, env, terminal, requested, agent, format, color) => {
        const mode = resolveMode(env, TERMINALS[terminal]!, requested as OutputFormat | undefined)
        expect(mode).toMatchObject({ agent, format, color })
    })
})

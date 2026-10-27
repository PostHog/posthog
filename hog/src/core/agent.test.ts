import { describe, expect, test } from 'bun:test'

import { resolveMode, type OutputFormat } from './agent'

describe('resolveMode', () => {
    test.each([
        ['a person at a terminal gets text with color', {}, true, undefined, undefined, 'text', true],
        ['a pipe gets json', {}, false, undefined, undefined, 'json', false],
        ['Claude Code gets json without color', { CLAUDECODE: '1' }, true, undefined, 'claude-code', 'json', false],
        [
            'Codex is detected by its sandbox variable',
            { CODEX_SANDBOX: 'seatbelt' },
            true,
            undefined,
            'codex',
            'json',
            false,
        ],
        ['AI_AGENT names the agent', { AI_AGENT: 'v0' }, true, undefined, 'v0', 'json', false],
        [
            'HOG_AGENT=0 overrides detection',
            { CLAUDECODE: '1', HOG_AGENT: '0' },
            true,
            undefined,
            undefined,
            'text',
            true,
        ],
        ['HOG_AGENT=1 forces agent mode', { HOG_AGENT: '1' }, true, undefined, 'unknown', 'json', false],
        ["Cursor's own terminal is not an agent", { CURSOR_TRACE_ID: 'abc' }, true, undefined, undefined, 'text', true],
        ['--output json wins at a terminal', {}, true, 'json', undefined, 'json', false],
        ['--output text for an agent stays uncolored', { CLAUDECODE: '1' }, true, 'text', 'claude-code', 'text', false],
        ['NO_COLOR turns color off', { NO_COLOR: '1' }, true, undefined, undefined, 'text', false],
    ] as const)('%s', (_name, env, tty, requested, agent, format, color) => {
        const mode = resolveMode(env, tty, requested as OutputFormat | undefined)
        expect(mode).toMatchObject({ agent, format, color })
    })
})

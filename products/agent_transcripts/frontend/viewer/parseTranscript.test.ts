import { parseTranscript } from './parseTranscript'

const jsonl = (...events: unknown[]): string => events.map((event) => JSON.stringify(event)).join('\n')

const claudeCodeSession = jsonl(
    { type: 'summary', summary: 'Set up analytics' },
    { type: 'user', uuid: 'u1', message: { role: 'user', content: 'Add PostHog to this app' } },
    {
        type: 'assistant',
        uuid: 'a1',
        message: { id: 'msg_1', role: 'assistant', content: [{ type: 'thinking', thinking: 'Check the framework' }] },
    },
    {
        type: 'assistant',
        uuid: 'a2',
        message: {
            id: 'msg_1',
            role: 'assistant',
            content: [{ type: 'tool_use', id: 'call_1', name: 'Bash', input: { command: 'cat package.json' } }],
        },
    },
    {
        type: 'user',
        uuid: 'u2',
        message: { role: 'user', content: [{ type: 'tool_result', tool_use_id: 'call_1', content: '{"name":"app"}' }] },
    },
    {
        type: 'assistant',
        uuid: 'a3',
        message: { id: 'msg_1', role: 'assistant', content: [{ type: 'text', text: 'Installed posthog-js.' }] },
    }
)

const codexSession = jsonl(
    { type: 'session_meta', payload: { id: 'session-1' } },
    {
        type: 'response_item',
        payload: { type: 'message', role: 'user', content: [{ type: 'input_text', text: '<environment_context>' }] },
    },
    {
        type: 'response_item',
        payload: { type: 'message', role: 'user', content: [{ type: 'input_text', text: 'Add PostHog' }] },
    },
    { type: 'event_msg', payload: { type: 'user_message', message: 'Add PostHog' } },
    { type: 'response_item', payload: { type: 'reasoning', summary: [{ type: 'summary_text', text: 'Look first' }] } },
    {
        type: 'response_item',
        payload: {
            type: 'function_call',
            name: 'shell',
            call_id: 'call_1',
            arguments: JSON.stringify({ command: ['bash', '-lc', 'npm test'] }),
        },
    },
    {
        type: 'response_item',
        payload: {
            type: 'function_call_output',
            call_id: 'call_1',
            output: JSON.stringify({ output: '1 failing', metadata: { exit_code: 1 } }),
        },
    },
    {
        type: 'response_item',
        payload: { type: 'message', role: 'assistant', content: [{ type: 'output_text', text: 'Done.' }] },
    }
)

const codexExecJson = jsonl(
    { type: 'thread.started', thread_id: 't1' },
    { type: 'item.completed', item: { id: 'i0', type: 'reasoning', text: 'Plan the change' } },
    {
        type: 'item.completed',
        item: { id: 'i1', type: 'command_execution', command: 'ls', aggregated_output: 'src', exit_code: 0 },
    },
    { type: 'item.completed', item: { id: 'i2', type: 'agent_message', text: 'Done.' } }
)

const cursorStreamJson = jsonl(
    { type: 'user', message: { role: 'user', content: [{ type: 'text', text: 'Add PostHog' }] } },
    {
        type: 'tool_call',
        subtype: 'started',
        call_id: 'c1',
        tool_call: { shellToolCall: { args: { command: 'pnpm add posthog-js' } } },
    },
    {
        type: 'tool_call',
        subtype: 'completed',
        call_id: 'c1',
        tool_call: {
            shellToolCall: {
                args: { command: 'pnpm add posthog-js' },
                result: { success: { stdout: 'added 1 package', exitCode: 0 } },
            },
        },
    },
    { type: 'assistant', message: { role: 'assistant', content: [{ type: 'text', text: 'Done.' }] } },
    { type: 'result', result: 'Done.' }
)

const chatGptExport = JSON.stringify([
    {
        title: 'PostHog setup',
        current_node: 'n3',
        mapping: {
            n0: { message: null, parent: null },
            n1: {
                parent: 'n0',
                message: { author: { role: 'system' }, content: { content_type: 'text', parts: [''] } },
            },
            n2: {
                parent: 'n1',
                message: { author: { role: 'user' }, content: { content_type: 'text', parts: ['Add PostHog'] } },
            },
            'n2-abandoned': {
                parent: 'n1',
                message: { author: { role: 'user' }, content: { content_type: 'text', parts: ['Edited away'] } },
            },
            n3: {
                parent: 'n2',
                message: {
                    author: { role: 'assistant' },
                    content: { content_type: 'text', parts: ['Run the Wizard.'] },
                },
            },
        },
    },
])

const claudeAppExport = JSON.stringify([
    {
        name: 'PostHog setup',
        chat_messages: [
            { sender: 'human', text: 'Add PostHog', content: [{ type: 'text', text: 'Add PostHog' }] },
            {
                sender: 'assistant',
                content: [
                    { type: 'tool_use', name: 'web_search', input: { query: 'posthog nextjs' } },
                    { type: 'tool_result', name: 'web_search', content: [{ type: 'text', text: 'posthog.com/docs' }] },
                    { type: 'text', text: 'Run the Wizard.' },
                ],
            },
        ],
    },
])

const cursorMarkdownExport = [
    '# PostHog setup',
    '',
    '_**User**_',
    '',
    'Add PostHog',
    '',
    '---',
    '',
    '_**Agent (claude-4-sonnet)**_',
    '',
    '## AI setup',
    'Run the Wizard.',
].join('\n')

const copiedConversation = 'Human: Add PostHog\n\nAssistant: Run the Wizard.\nYou can also install it by hand.'

describe('parseTranscript', () => {
    test.each([
        [
            'Claude Code session file',
            claudeCodeSession,
            [
                ['user', '', 'Add PostHog to this app', ''],
                ['thinking', '', 'Check the framework', ''],
                ['tool', 'Bash', 'cat package.json', '{"name":"app"}', 'passed'],
                ['message', '', 'Installed posthog-js.', ''],
            ],
        ],
        [
            'Codex session file',
            codexSession,
            [
                ['system', 'Context', '<environment_context>', ''],
                ['user', '', 'Add PostHog', ''],
                ['thinking', '', 'Look first', ''],
                ['tool', 'shell', 'npm test', '1 failing', 'failed'],
                ['message', '', 'Done.', ''],
            ],
        ],
        [
            'Codex exec JSON',
            codexExecJson,
            [
                ['thinking', '', 'Plan the change', ''],
                ['tool', 'shell', 'ls', 'src', 'passed'],
                ['message', '', 'Done.', ''],
            ],
        ],
        [
            'Cursor CLI stream JSON',
            cursorStreamJson,
            [
                ['user', '', 'Add PostHog', ''],
                ['tool', 'shell', 'pnpm add posthog-js', 'added 1 package', 'passed'],
                ['message', '', 'Done.', ''],
            ],
        ],
        [
            'ChatGPT export',
            chatGptExport,
            [
                ['user', '', 'Add PostHog', ''],
                ['message', '', 'Run the Wizard.', ''],
            ],
        ],
        [
            'Claude app export',
            claudeAppExport,
            [
                ['user', '', 'Add PostHog', ''],
                ['web', 'web_search', 'posthog nextjs', 'posthog.com/docs', 'passed'],
                ['message', '', 'Run the Wizard.', ''],
            ],
        ],
        [
            'Cursor Markdown export',
            cursorMarkdownExport,
            [
                ['user', '', 'Add PostHog', ''],
                ['message', '', '## AI setup\nRun the Wizard.', ''],
            ],
        ],
        [
            'copied conversation',
            copiedConversation,
            [
                ['user', '', 'Add PostHog', ''],
                ['message', '', 'Run the Wizard.\nYou can also install it by hand.', ''],
            ],
        ],
        ['text without speakers', 'Notes about the setup', [['message', '', 'Notes about the setup', '']]],
    ])('reads a %s', (_format, text, expected) => {
        const entries = parseTranscript(text).map(({ kind, title, text, output, status }) =>
            [kind, title, text, output ?? '', status].filter((value) => value !== undefined)
        )

        expect(entries).toEqual(expected)
    })
})

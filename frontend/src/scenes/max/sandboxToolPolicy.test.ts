import {
    defaultPermissionDecision,
    findAllowOptionId,
    isPostHogDestructiveSubTool,
    isPostHogExecTool,
    type PermissionDecision,
} from './sandboxToolPolicy'
import type { PermissionRequestRecord, ToolInvocation } from './types/sandboxStreamTypes'
import type { PermissionOption } from './types/sandboxWireTypes'

function makeRecord(
    overrides: { toolName?: string; resolvedKey?: string; innerToolName?: string; options?: PermissionOption[] } = {}
): PermissionRequestRecord {
    const rawToolCall: ToolInvocation = {
        toolCallId: 'tc',
        rawServerName: 'posthog',
        rawToolName: 'exec',
        resolvedKey: overrides.resolvedKey ?? 'exec',
        innerToolName: overrides.innerToolName,
        input: {},
        status: 'pending',
        contentBlocks: [],
    }
    return {
        requestId: 'r',
        toolCallId: 'tc',
        toolName: overrides.toolName ?? 'mcp__posthog__exec',
        options: overrides.options ?? [{ optionId: 'allow', name: 'Yes', kind: 'allow_once' }],
        rawToolCall,
    }
}

describe('sandboxToolPolicy', () => {
    describe('isPostHogExecTool', () => {
        it.each([
            ['mcp__posthog__exec', true],
            ['mcp__posthog_us__exec', true],
            ['mcp__posthog__query', false],
            ['Bash', false],
        ])('%s → %s', (name, expected) => {
            expect(isPostHogExecTool(name)).toEqual(expected)
        })
    })

    describe('isPostHogDestructiveSubTool', () => {
        // Cases ported from Twig posthog-exec-gate.test.ts.
        it.each([
            'experiment-update',
            'feature-flag-delete',
            'notebooks-destroy',
            'experiment-partial-update',
            'update-something',
            'delete',
        ])('%s is destructive', (sub) => expect(isPostHogDestructiveSubTool(sub)).toBe(true))
        it.each(['experiment-get', 'feature-flag-list', 'experiment-create', 'insights-pause', 'get-updated-events'])(
            '%s is not destructive',
            (sub) => expect(isPostHogDestructiveSubTool(sub)).toBe(false)
        )
    })

    describe('defaultPermissionDecision', () => {
        it.each<[string, PermissionRequestRecord, PermissionDecision]>([
            ['built-in tool', makeRecord({ toolName: 'Bash', resolvedKey: 'Bash' }), 'auto_allow'],
            ['exec discovery verb', makeRecord({ resolvedKey: '__posthog_exec_tools__' }), 'auto_allow'],
            [
                'exec create',
                makeRecord({ resolvedKey: 'insight-create', innerToolName: 'insight-create' }),
                'auto_allow',
            ],
            ['exec update', makeRecord({ resolvedKey: 'insight-update', innerToolName: 'insight-update' }), 'prompt'],
            [
                'exec delete',
                makeRecord({ resolvedKey: 'feature-flag-delete', innerToolName: 'feature-flag-delete' }),
                'prompt',
            ],
            ['other mcp tool', makeRecord({ toolName: 'mcp__other__foo', resolvedKey: 'foo' }), 'prompt'],
        ])('%s → %s', (_case, record, expected) => {
            expect(defaultPermissionDecision(record)).toEqual(expected)
        })
    })

    describe('findAllowOptionId', () => {
        it('prefers allow_once over allow_always', () => {
            const id = findAllowOptionId(
                makeRecord({
                    options: [
                        { optionId: 'aa', name: '', kind: 'allow_always' },
                        { optionId: 'a1', name: '', kind: 'allow_once' },
                    ],
                })
            )
            expect(id).toEqual('a1')
        })

        it('falls back to allow_always when there is no allow_once', () => {
            const id = findAllowOptionId(
                makeRecord({
                    options: [
                        { optionId: 'aa', name: '', kind: 'allow_always' },
                        { optionId: 'r', name: '', kind: 'reject_once' },
                    ],
                })
            )
            expect(id).toEqual('aa')
        })

        it('returns null when no allow option exists', () => {
            expect(
                findAllowOptionId(makeRecord({ options: [{ optionId: 'r', name: '', kind: 'reject_once' }] }))
            ).toBeNull()
        })
    })
})

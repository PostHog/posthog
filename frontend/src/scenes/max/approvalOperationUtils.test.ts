import { permissionRequestToPendingApproval, pickPermissionOptionId } from './approvalOperationUtils'
import { PermissionOption, PermissionRequestRecord, ToolInvocation } from './types/sandboxStreamTypes'

describe('approvalOperationUtils — sandbox permission mapping', () => {
    function toolInvocation(overrides: Partial<ToolInvocation> = {}): ToolInvocation {
        return {
            toolCallId: 'tc-1',
            rawServerName: 'posthog',
            rawToolName: 'execute_sql',
            innerToolName: 'execute_sql',
            resolvedKey: 'posthog/execute_sql',
            input: { query: 'DROP TABLE x' },
            innerInput: { query: 'DROP TABLE x' },
            status: 'pending',
            contentBlocks: [],
            ...overrides,
        }
    }

    function record(overrides: Partial<PermissionRequestRecord> = {}): PermissionRequestRecord {
        return {
            requestId: 'req-1',
            toolCallId: 'tc-1',
            options: [
                { optionId: 'opt-allow', name: 'Allow', kind: 'allow_once' },
                { optionId: 'opt-reject', name: 'Reject', kind: 'reject' },
            ],
            description: 'Run a dangerous query',
            rawToolCall: toolInvocation(),
            ...overrides,
        }
    }

    describe('permissionRequestToPendingApproval', () => {
        it('maps onto the existing PendingApproval shape keyed for the card, carrying options[]', () => {
            const approval = permissionRequestToPendingApproval(record())
            expect(approval.proposal_id).toBe('req-1')
            expect(approval.decision_status).toBe('pending')
            expect(approval.original_tool_call_id).toBe('tc-1')
            expect(approval.tool_name).toBe('posthog/execute_sql')
            expect(approval.preview).toBe('Run a dangerous query')
            expect(approval.payload.options).toHaveLength(2)
            expect(approval.payload.tool_call_id).toBe('tc-1')
        })

        it('falls back to the tool title for the preview when no description is present', () => {
            const approval = permissionRequestToPendingApproval(
                record({ description: undefined, title: undefined, rawToolCall: toolInvocation({ title: 'My tool' }) })
            )
            expect(approval.preview).toBe('My tool')
        })

        it('carries the remember flag through to the payload (drives the Always-allow affordance)', () => {
            expect(permissionRequestToPendingApproval(record({ remember: true })).payload.remember).toBe(true)
            expect(permissionRequestToPendingApproval(record({ remember: undefined })).payload.remember).toBe(false)
        })
    })

    describe('pickPermissionOptionId', () => {
        const options: PermissionOption[] = [
            { optionId: 'opt-allow', name: 'Allow', kind: 'allow_once' },
            { optionId: 'opt-allow-always', name: 'Always allow', kind: 'allow_always' },
            { optionId: 'opt-reject', name: 'Reject', kind: 'reject' },
            { optionId: 'opt-reject-feedback', name: 'Refine', kind: 'reject_with_feedback' },
        ]

        it('approve picks the allow_once option', () => {
            expect(pickPermissionOptionId(options, 'approve', false)).toBe('opt-allow')
        })

        it('approve falls back to allow_always when no allow_once exists', () => {
            const onlyAlways = options.filter((o) => o.kind !== 'allow_once')
            expect(pickPermissionOptionId(onlyAlways, 'approve', false)).toBe('opt-allow-always')
        })

        it('approve with remember picks the allow_always option', () => {
            expect(pickPermissionOptionId(options, 'approve', false, true)).toBe('opt-allow-always')
        })

        it('approve with remember falls back to allow_once when no allow_always exists', () => {
            const noAlways = options.filter((o) => o.kind !== 'allow_always')
            expect(pickPermissionOptionId(noAlways, 'approve', false, true)).toBe('opt-allow')
        })

        it('reject without feedback picks the plain reject option', () => {
            expect(pickPermissionOptionId(options, 'reject', false)).toBe('opt-reject')
        })

        it('reject with feedback prefers the reject_with_feedback option', () => {
            expect(pickPermissionOptionId(options, 'reject', true)).toBe('opt-reject-feedback')
        })

        it('returns null when no matching option exists', () => {
            expect(pickPermissionOptionId([], 'approve', false)).toBeNull()
        })
    })
})

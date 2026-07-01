import { describe, expect, it } from 'vitest'

import { ApprovalTypeSchema } from '../spec/spec'
import { effectiveApprovalType } from './approval-store'

describe('approval-authority totality', () => {
    it('every concrete ApprovalType round-trips (no silent downgrade)', () => {
        for (const type of ApprovalTypeSchema.options) {
            const resolved = effectiveApprovalType({ type, allow_edit: false })
            expect(resolved, `authority "${type}" must resolve to itself, not the default gate`).toBe(type)
        }
    })

    it('a legacy team_admins scope resolves to the owner gate (agent)', () => {
        const legacy = { approvers: ['team_admins'] } as never
        expect(effectiveApprovalType(legacy)).toBe('agent')
    })
})

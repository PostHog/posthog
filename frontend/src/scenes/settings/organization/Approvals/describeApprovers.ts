import { ApprovalPolicy } from '~/types'

export function describeApprovers(policy: ApprovalPolicy): string {
    const users = policy.approver_config?.users || []
    const roles = policy.approver_config?.roles || []
    const parts = []
    if (users.length > 0) {
        parts.push(`${users.length} user${users.length > 1 ? 's' : ''}`)
    }
    if (roles.length > 0) {
        parts.push(`${roles.length} role${roles.length > 1 ? 's' : ''}`)
    }
    return parts.join(', ') || 'None'
}

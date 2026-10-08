export type AssignmentStatus = 'all' | 'assigned' | 'unassigned'

export function isAssignmentStatus(value: unknown): value is AssignmentStatus {
    return value === 'all' || value === 'assigned' || value === 'unassigned'
}

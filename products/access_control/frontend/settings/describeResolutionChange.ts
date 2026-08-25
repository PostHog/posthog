import { ResolutionChange, ResolutionChangeLevel } from './resolutionPreviewLogic'

export function humanLevel(level: string): string {
    return level === 'none' ? 'No access' : level.charAt(0).toUpperCase() + level.slice(1)
}

function describeResolved(resolved: ResolutionChangeLevel): string {
    const level = humanLevel(resolved.level)
    switch (resolved.source) {
        case 'object':
            if (resolved.source_subject === 'member') {
                return `their own override on this object (${level})`
            }
            if (resolved.source_subject === 'role') {
                return `the role's rule on this object (${level})`
            }
            return `this object's own level (${level})`
        case 'parent_object':
            return `the rule on its source (${level})`
        case 'resource':
            if (resolved.source_subject === 'member') {
                return `their own resource-level setting (${level})`
            }
            if (resolved.source_subject === 'role') {
                return `the role's resource-level setting (${level})`
            }
            return `the resource-level setting (${level})`
        case 'parent_resource':
            return `the resource-level setting of its source (${level})`
        default:
            return `the built-in default (${level})`
    }
}

export function describeResolutionChange(change: ResolutionChange): string {
    return `Today ${describeResolved(change.current)} applies. After the change, ${describeResolved(
        change.proposed
    )} applies.`
}

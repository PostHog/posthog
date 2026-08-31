import { ResolutionChange, ResolutionChangeLevel } from './resolutionPreviewLogic'

export function humanLevel(level: string): string {
    return level === 'none' ? 'No access' : level.charAt(0).toUpperCase() + level.slice(1)
}

function scopePhrase(change: ResolutionChange, resolved: ResolutionChangeLevel): string {
    switch (resolved.source) {
        case 'object':
            return change.scope === 'object' ? 'level on this object' : 'object-level rule'
        case 'parent_object':
            return 'rule on its source'
        case 'resource':
            return 'resource-level setting'
        case 'parent_resource':
            return 'resource-level setting of its source'
        default:
            return 'built-in default'
    }
}

function describeResolved(change: ResolutionChange, resolved: ResolutionChangeLevel): string {
    const level = humanLevel(resolved.level)
    const phrase = scopePhrase(change, resolved)
    if (resolved.source_subject === 'member') {
        const owner = change.subject.type === 'member' ? 'their own' : `${resolved.subject_name ?? 'a member'}'s`
        return `${owner} ${phrase} (${level})`
    }
    if (resolved.source_subject === 'role') {
        const owner =
            change.subject.type === 'role'
                ? "the role's"
                : resolved.subject_name
                  ? `the ${resolved.subject_name} role's`
                  : "a role's"
        return `${owner} ${phrase} (${level})`
    }
    if (resolved.source === 'object' || resolved.source === 'parent_object') {
        return `the default ${phrase} (${level})`
    }
    return `the ${phrase} (${level})`
}

function describeShort(change: ResolutionChange, resolved: ResolutionChangeLevel): string {
    if (resolved.source_subject === 'member') {
        return change.subject.type === 'member'
            ? 'their own setting'
            : `${resolved.subject_name ?? 'the member'}'s setting`
    }
    if (resolved.source_subject === 'role') {
        return change.subject.type === 'role'
            ? "the role's own setting"
            : `the ${resolved.subject_name ?? ''} role's setting`
    }
    return `the ${scopePhrase(change, resolved)}`
}

export function describeResolutionChange(change: ResolutionChange): string {
    // "Dana Kim holds the Engineers role." when a role's grant decides for a member today
    const intro =
        change.subject.type === 'member' && change.current.source_subject === 'role' && change.current.subject_name
            ? `${change.subject.name} holds the ${change.current.subject_name} role. `
            : ''
    const today = describeResolved(change, change.current)
    const proposed = describeResolved(change, change.proposed)
    const after = describeShort(change, change.proposed)
    return `${intro}Today ${today} applies over ${proposed}. After the change, ${after} applies.`
}

import { APIScopeObject, AccessControlLevel, EffectiveAccessControlEntry } from '~/types'

type InheritedAccess = NonNullable<EffectiveAccessControlEntry['inherited_access']>

/** An inherited_access value in wire vocabulary: the level plus which rule decided it. */
export function inheritedAccess(
    level: AccessControlLevel,
    source: InheritedAccess['source'] = 'resource',
    source_subject: InheritedAccess['source_subject'] = 'default',
    source_resource: APIScopeObject = 'dashboard' as APIScopeObject
): InheritedAccess {
    return { access_level: level, source, source_subject, source_resource, source_resource_id: null }
}

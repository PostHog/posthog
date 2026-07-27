// Per-dispatch context. The role is the only thing that flows parent → child;
// everything else a rule needs comes from `input`.

import { normalizeRole, roleMap } from '../../utils'

export class Scope {
    private constructor(
        readonly input: unknown,
        readonly role: string
    ) {}

    static forNode(input: unknown, inheritedRole: string): Scope {
        return new Scope(input, resolveRole(input, inheritedRole))
    }

    // Re-roots on an array element without re-resolving the role — the element is
    // a value to read fields off, not a new message.
    withInput(input: unknown): Scope {
        return new Scope(input, this.role)
    }
}

function resolveRole(input: unknown, inheritedRole: string): string {
    if (!input || typeof input !== 'object') {
        return inheritedRole
    }
    const obj = input as Record<string, unknown>
    if (typeof obj.role === 'string') {
        return normalizeRole(obj.role, inheritedRole)
    }
    if (typeof obj.type === 'string' && Object.hasOwn(roleMap, obj.type)) {
        return normalizeRole(obj.type, inheritedRole)
    }
    return inheritedRole
}

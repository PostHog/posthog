import { formatHclValue, sanitizeResourceName } from 'lib/components/TerraformExporter/hclExporterFormattingUtils'

import { AccessControlTypeBase } from '~/types'

import type {
    OrganizationMemberApi,
    RoleApi,
    UserBasicApi,
} from 'products/platform_features/frontend/generated/api.schemas'

import { FieldMapping, HclExportOptions, HclExportResult, ResourceExporter, generateHCL } from './hclExporter'

export type AccessControlRule = Pick<
    AccessControlTypeBase,
    'resource' | 'access_level' | 'role' | 'organization_member'
> & { resource_id: string | null }

type ExportedRole = Pick<RoleApi, 'id' | 'name'>
type ExportedMember = Pick<OrganizationMemberApi, 'id'> & { user: Pick<UserBasicApi, 'email'> }

export interface AccessControlExportInput {
    projectId: number
    organizationId: string
    /** Rules on the project itself: the default project access, plus role and member project access */
    projectRules: AccessControlRule[]
    /** Rules that apply to a whole resource type, such as every feature flag */
    resourceRules: AccessControlRule[]
    roles: ExportedRole[]
    members: ExportedMember[]
}

export interface AccessControlExportResult extends HclExportResult {
    resourceCounts: {
        roles: number
        members: number
        rules: number
    }
}

interface RuleHclOptions extends HclExportOptions {
    /** A rule's role id rendered as a reference to the exported role block, or the raw id when the role was not found */
    roleRef: (id: string) => string
    memberRef: (id: string) => string
}

const ROLE_FIELD_MAPPINGS: FieldMapping<ExportedRole>[] = [{ source: 'name', target: 'name' }]

const SUBJECT_FIELD_MAPPINGS: FieldMapping<AccessControlRule, RuleHclOptions>[] = [
    {
        source: 'role',
        target: 'role',
        shouldInclude: (v) => !!v,
        transform: (v, _rule, options) => options.roleRef(String(v)),
    },
    {
        source: 'organization_member',
        target: 'organization_member',
        shouldInclude: (v) => !!v,
        transform: (v, _rule, options) => options.memberRef(String(v)),
    },
]

/** @see https://registry.terraform.io/providers/PostHog/posthog/latest/docs/resources/project_default_access */
const PROJECT_DEFAULT_ACCESS_FIELD_MAPPINGS: FieldMapping<AccessControlRule, RuleHclOptions>[] = [
    { source: 'access_level', target: 'access_level' },
]

/** @see https://registry.terraform.io/providers/PostHog/posthog/latest/docs/resources/project_member */
const PROJECT_MEMBER_FIELD_MAPPINGS: FieldMapping<AccessControlRule, RuleHclOptions>[] = [
    ...SUBJECT_FIELD_MAPPINGS,
    { source: 'access_level', target: 'access_level' },
]

/** @see https://registry.terraform.io/providers/PostHog/posthog/latest/docs/resources/access_control */
const ACCESS_CONTROL_FIELD_MAPPINGS: FieldMapping<AccessControlRule, RuleHclOptions>[] = [
    { source: 'resource', target: 'resource' },
    { source: 'access_level', target: 'access_level' },
    ...SUBJECT_FIELD_MAPPINGS,
]

/** Terraform block names must be unique in a file, and two subjects can sanitize to the same name */
class NameRegistry {
    private used = new Set<string>()

    claim(name: string, fallback: string): string {
        const base = sanitizeResourceName(name, fallback)
        let candidate = base
        let suffix = 2
        while (this.used.has(candidate)) {
            candidate = `${base}_${suffix++}`
        }
        this.used.add(candidate)
        return candidate
    }
}

/** The name and import id are decided before the block renders, so the exporter only has to echo them back */
function exporterFor<T, O extends HclExportOptions>(
    resourceType: string,
    resourceLabel: string,
    fieldMappings: FieldMapping<T, O>[],
    name: string,
    importId: string
): ResourceExporter<T, O> {
    return {
        resourceType,
        resourceLabel,
        fieldMappings,
        validate: () => [],
        getResourceName: () => name,
        getId: () => importId,
    }
}

function userDataBlock(name: string, email: string): string {
    return [`data "posthog_user" "${name}" {`, `  email = ${formatHclValue(email)}`, '}'].join('\n')
}

export function generateAccessControlHCL(input: AccessControlExportInput): AccessControlExportResult {
    const { projectId, organizationId } = input
    const names = new NameRegistry()
    const warnings: string[] = []
    const sections: string[] = []

    const rules = [...input.projectRules, ...input.resourceRules].filter((rule) => rule.access_level !== null)
    const rolesById = new Map(input.roles.map((role) => [role.id, role]))
    const membersById = new Map(input.members.map((member) => [member.id, member]))

    // Only the roles and members that a rule points at, so the file stays scoped to this project
    const roleRefs = new Map<string, string>()
    for (const roleId of new Set(rules.map((rule) => rule.role).filter((id): id is string => !!id))) {
        const role = rolesById.get(roleId)
        if (!role) {
            warnings.push(`Role ${roleId} was not found. Its rules use the raw role ID.`)
            continue
        }
        const name = names.claim(`role_${role.name}`, 'role')
        const exporter = exporterFor('posthog_role', 'role', ROLE_FIELD_MAPPINGS, name, `${organizationId}/${role.id}`)
        sections.push(generateHCL(role, exporter).hcl)
        roleRefs.set(roleId, `${exporter.resourceType}.${name}.id`)
    }

    const memberRefs = new Map<string, string>()
    for (const memberId of new Set(rules.map((rule) => rule.organization_member).filter((id): id is string => !!id))) {
        const member = membersById.get(memberId)
        if (!member) {
            warnings.push(`Organization member ${memberId} was not found. Their rules use the raw member ID.`)
            continue
        }
        const name = names.claim(`user_${member.user.email}`, 'user')
        sections.push(userDataBlock(name, member.user.email))
        memberRefs.set(memberId, `data.posthog_user.${name}.organization_member_id`)
    }

    const options: RuleHclOptions = {
        roleRef: (id) => roleRefs.get(id) ?? formatHclValue(id),
        memberRef: (id) => memberRefs.get(id) ?? formatHclValue(id),
    }
    const subjectLabel = (rule: AccessControlRule): string => {
        if (rule.role) {
            return `role_${rolesById.get(rule.role)?.name ?? rule.role}`
        }
        if (rule.organization_member) {
            return `user_${membersById.get(rule.organization_member)?.user.email ?? rule.organization_member}`
        }
        return 'default'
    }
    const subjectImportPath = (rule: AccessControlRule): string =>
        rule.role ? `role/${rule.role}` : rule.organization_member ? `member/${rule.organization_member}` : 'default'

    for (const rule of input.projectRules) {
        if (rule.access_level === null) {
            continue
        }
        const exporter =
            !rule.role && !rule.organization_member
                ? exporterFor(
                      'posthog_project_default_access',
                      'project default access',
                      PROJECT_DEFAULT_ACCESS_FIELD_MAPPINGS,
                      names.claim('project_default', 'project_default'),
                      `${projectId}`
                  )
                : exporterFor(
                      'posthog_project_member',
                      'project member',
                      PROJECT_MEMBER_FIELD_MAPPINGS,
                      names.claim(`project_${subjectLabel(rule)}`, 'project_member'),
                      `${projectId}/${subjectImportPath(rule)}`
                  )
        sections.push(generateHCL(rule, exporter, options).hcl)
    }

    for (const rule of input.resourceRules) {
        if (rule.access_level === null) {
            continue
        }
        const exporter = exporterFor(
            'posthog_access_control',
            'access control',
            ACCESS_CONTROL_FIELD_MAPPINGS,
            names.claim(`${rule.resource}_${subjectLabel(rule)}`, 'access_control'),
            `${projectId}/${rule.resource}/${subjectImportPath(rule)}`
        )
        sections.push(generateHCL(rule, exporter, options).hcl)
    }

    return {
        hcl: sections.join('\n\n') + '\n',
        warnings,
        resourceCounts: { roles: roleRefs.size, members: memberRefs.size, rules: rules.length },
    }
}

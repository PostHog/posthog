import { formatHclValue, sanitizeResourceName } from 'lib/components/TerraformExporter/hclExporterFormattingUtils'

import { AccessControlType, OrganizationMemberType, RoleType } from '~/types'

import { HclExportResult, POSTHOG_PROVIDER_VERSION } from './hclExporter'

export type AccessControlRule = AccessControlType & { resource_id: string | null }

export interface AccessControlExportInput {
    projectId: number
    organizationId: string
    /** Rules on the project itself: the default project access, plus role and member project access */
    projectRules: AccessControlRule[]
    /** Rules that apply to a whole resource type, such as every feature flag */
    resourceRules: AccessControlRule[]
    roles: RoleType[]
    members: OrganizationMemberType[]
}

export interface AccessControlExportResult extends HclExportResult {
    resourceCounts: {
        roles: number
        members: number
        rules: number
    }
}

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

function importBlock(address: string, id: string): string[] {
    return ['import {', `  to = ${address}`, `  id = ${formatHclValue(id)}`, '}', '']
}

/**
 * @see https://registry.terraform.io/providers/PostHog/posthog/latest/docs/resources/access_control
 * @see https://registry.terraform.io/providers/PostHog/posthog/latest/docs/resources/project_member
 * @see https://registry.terraform.io/providers/PostHog/posthog/latest/docs/resources/project_default_access
 */
export function generateAccessControlHCL(input: AccessControlExportInput): AccessControlExportResult {
    const { projectId, organizationId } = input
    const names = new NameRegistry()
    const warnings: string[] = []
    const lines: string[] = [
        `# Terraform configuration for PostHog access control`,
        `# Compatible with posthog provider v${POSTHOG_PROVIDER_VERSION}`,
        `# Source project ID: ${projectId}`,
        '',
    ]

    const rules = [...input.projectRules, ...input.resourceRules].filter((rule) => rule.access_level !== null)

    // Only the roles and members that a rule points at, so the file stays scoped to this project
    const roleIds = new Set(rules.map((rule) => rule.role).filter((id): id is string => !!id))
    const memberIds = new Set(rules.map((rule) => rule.organization_member).filter((id): id is string => !!id))

    const roleRefs = new Map<string, string>()
    const rolesById = new Map(input.roles.map((role) => [role.id, role]))
    for (const roleId of roleIds) {
        const role = rolesById.get(roleId)
        if (!role) {
            warnings.push(`Role ${roleId} was not found. Its rules use the raw role ID.`)
            continue
        }
        const name = names.claim(`role_${role.name}`, 'role')
        lines.push(...importBlock(`posthog_role.${name}`, `${organizationId}/${role.id}`))
        lines.push(`resource "posthog_role" "${name}" {`, `  name = ${formatHclValue(role.name)}`, '}', '')
        roleRefs.set(roleId, `posthog_role.${name}.id`)
    }

    const memberRefs = new Map<string, string>()
    const membersById = new Map(input.members.map((member) => [member.id, member]))
    for (const memberId of memberIds) {
        const member = membersById.get(memberId)
        if (!member) {
            warnings.push(`Organization member ${memberId} was not found. Their rules use the raw member ID.`)
            continue
        }
        const name = names.claim(`user_${member.user.email}`, 'user')
        lines.push(`data "posthog_user" "${name}" {`, `  email = ${formatHclValue(member.user.email)}`, '}', '')
        memberRefs.set(memberId, `data.posthog_user.${name}.organization_member_id`)
    }

    const roleRef = (id: string): string => roleRefs.get(id) ?? formatHclValue(id)
    const memberRef = (id: string): string => memberRefs.get(id) ?? formatHclValue(id)
    const subjectLabel = (rule: AccessControlRule): string => {
        if (rule.role) {
            return `role_${rolesById.get(rule.role)?.name ?? rule.role}`
        }
        if (rule.organization_member) {
            return `user_${membersById.get(rule.organization_member)?.user.email ?? rule.organization_member}`
        }
        return 'default'
    }

    for (const rule of input.projectRules) {
        if (rule.access_level === null) {
            continue
        }
        if (!rule.role && !rule.organization_member) {
            const name = names.claim('project_default', 'project_default')
            lines.push(...importBlock(`posthog_project_default_access.${name}`, `${projectId}`))
            lines.push(
                `resource "posthog_project_default_access" "${name}" {`,
                `  access_level = ${formatHclValue(rule.access_level)}`,
                '}',
                ''
            )
            continue
        }
        const name = names.claim(`project_${subjectLabel(rule)}`, 'project_member')
        const importId = rule.role
            ? `${projectId}/role/${rule.role}`
            : `${projectId}/member/${rule.organization_member}`
        lines.push(...importBlock(`posthog_project_member.${name}`, importId))
        lines.push(`resource "posthog_project_member" "${name}" {`)
        if (rule.role) {
            lines.push(`  role         = ${roleRef(rule.role)}`)
        } else if (rule.organization_member) {
            lines.push(`  organization_member = ${memberRef(rule.organization_member)}`)
        }
        lines.push(`  access_level = ${formatHclValue(rule.access_level)}`, '}', '')
    }

    for (const rule of input.resourceRules) {
        if (rule.access_level === null) {
            continue
        }
        const name = names.claim(`${rule.resource}_${subjectLabel(rule)}`, 'access_control')
        const target = rule.role
            ? `role/${rule.role}`
            : rule.organization_member
              ? `member/${rule.organization_member}`
              : 'default'
        lines.push(...importBlock(`posthog_access_control.${name}`, `${projectId}/${rule.resource}/${target}`))
        lines.push(
            `resource "posthog_access_control" "${name}" {`,
            `  resource     = ${formatHclValue(rule.resource)}`,
            `  access_level = ${formatHclValue(rule.access_level)}`
        )
        if (rule.role) {
            lines.push(`  role         = ${roleRef(rule.role)}`)
        } else if (rule.organization_member) {
            lines.push(`  organization_member = ${memberRef(rule.organization_member)}`)
        }
        lines.push('}', '')
    }

    return {
        hcl: lines.join('\n').trimEnd() + '\n',
        warnings,
        resourceCounts: { roles: roleRefs.size, members: memberRefs.size, rules: rules.length },
    }
}

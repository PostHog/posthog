import { AccessControlExportInput, AccessControlRule, generateAccessControlHCL } from './accessControlHclExporter'

const ROLE_ID = '01a12045-1f02-0000-85fd-48fdffc811d0'
const MEMBER_ID = '01a11fff-4bae-0000-156d-42c3d14846a1'
const ORGANIZATION_ID = '01a11fff-3156-0000-f520-2de871c78629'

function rule(overrides: Partial<AccessControlRule>): AccessControlRule {
    return {
        resource: 'feature_flag',
        resource_id: null,
        access_level: 'viewer',
        role: null,
        organization_member: null,
        ...overrides,
    } as AccessControlRule
}

function exportRules(rules: Pick<AccessControlExportInput, 'projectRules' | 'resourceRules'>): string {
    return generateAccessControlHCL({
        projectId: 73,
        organizationId: ORGANIZATION_ID,
        roles: [{ id: ROLE_ID, name: 'Flag editors' }],
        members: [{ id: MEMBER_ID, user: { email: 'teammate@example.com' } }],
        ...rules,
    }).hcl
}

describe('generateAccessControlHCL', () => {
    test.each([
        {
            name: 'project default access',
            input: { projectRules: [rule({ resource: 'project', resource_id: '73' })], resourceRules: [] },
            expected: ['id = "73"', 'resource "posthog_project_default_access"'],
        },
        {
            name: 'role project access',
            input: {
                projectRules: [rule({ resource: 'project', resource_id: '73', access_level: 'admin', role: ROLE_ID })],
                resourceRules: [],
            },
            expected: [`id = "73/role/${ROLE_ID}"`, 'role         = posthog_role.role_flag_editors.id'],
        },
        {
            name: 'member project access',
            input: {
                projectRules: [rule({ resource: 'project', resource_id: '73', organization_member: MEMBER_ID })],
                resourceRules: [],
            },
            expected: [
                `id = "73/member/${MEMBER_ID}"`,
                'organization_member = data.posthog_user.user_teammate_example_com.organization_member_id',
            ],
        },
        {
            name: 'resource default',
            input: { projectRules: [], resourceRules: [rule({})] },
            expected: ['id = "73/feature_flag/default"', 'resource     = "feature_flag"'],
        },
        {
            name: 'role resource rule',
            input: { projectRules: [], resourceRules: [rule({ access_level: 'editor', role: ROLE_ID })] },
            expected: [
                `id = "${ORGANIZATION_ID}/${ROLE_ID}"`,
                `id = "73/feature_flag/role/${ROLE_ID}"`,
                'role         = posthog_role.role_flag_editors.id',
            ],
        },
        {
            name: 'member resource rule',
            input: { projectRules: [], resourceRules: [rule({ organization_member: MEMBER_ID })] },
            expected: [
                'email = "teammate@example.com"',
                `id = "73/feature_flag/member/${MEMBER_ID}"`,
                'organization_member = data.posthog_user.user_teammate_example_com.organization_member_id',
            ],
        },
    ])('exports $name with the import id the provider expects', ({ input, expected }) => {
        const hcl = exportRules(input)
        for (const line of expected) {
            expect(hcl).toContain(line)
        }
    })

    it('skips cleared rules and keeps unused roles out of the file', () => {
        const hcl = exportRules({ projectRules: [], resourceRules: [rule({ access_level: null, role: ROLE_ID })] })
        expect(hcl).not.toContain('posthog_access_control')
        expect(hcl).not.toContain('posthog_role')
    })
})

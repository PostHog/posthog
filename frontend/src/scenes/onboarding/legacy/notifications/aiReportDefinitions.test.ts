import { UserRole } from '~/types'

import { AI_REPORTS_BY_ROLE, reportForRole } from './aiReportDefinitions'

describe('aiReportDefinitions', () => {
    // Catches a new UserRole enum value silently losing its mapping at runtime (the Record type
    // enforces it at compile time, but `reportForRole` takes an untyped string from the user object).
    it.each([...Object.values(UserRole), null, undefined, 'not-a-role'])(
        'returns a complete definition for role %s',
        (role) => {
            const report = reportForRole(role)
            expect(report.key).toBeTruthy()
            expect(report.title).toBeTruthy()
            expect(report.headline).toBeTruthy()
            expect(report.prompt.length).toBeGreaterThan(100)
        }
    )

    it('gives founders and engineers the same revenue and growth report', () => {
        expect(AI_REPORTS_BY_ROLE[UserRole.Founder]).toBe(AI_REPORTS_BY_ROLE[UserRole.Engineering])
    })

    // "Self-driving" is an existing onboarding variant and brand term; this copy must never be
    // mistaken for it (explicit request from the feature discussion).
    it('never uses the term self-driving in any user-facing string', () => {
        for (const report of Object.values(AI_REPORTS_BY_ROLE)) {
            for (const text of [report.headline, report.lead, report.title, report.prompt]) {
                expect(text.toLowerCase()).not.toContain('self-driving')
            }
        }
    })
})

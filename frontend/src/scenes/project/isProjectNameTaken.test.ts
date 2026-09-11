import { ProjectBasicType } from '~/types'

import { isProjectNameTaken } from './isProjectNameTaken'

const project = (id: number, name: string): ProjectBasicType => ({ id, name, organization_id: 'org-1' })

describe('isProjectNameTaken', () => {
    const projects = [project(1, 'Marketing site'), project(2, '  Mobile app  ')]

    test.each([
        { scenario: 'an exact match', candidate: 'Marketing site', options: {}, expected: true },
        { scenario: 'a different case', candidate: 'marketing SITE', options: {}, expected: true },
        { scenario: 'padding around the candidate', candidate: '  Marketing site  ', options: {}, expected: true },
        { scenario: 'padding around the stored name', candidate: 'Mobile app', options: {}, expected: true },
        { scenario: 'a free name', candidate: 'Docs', options: {}, expected: false },
        {
            scenario: 'the project being renamed itself',
            candidate: 'Marketing site',
            options: { excludeProjectId: 1 },
            expected: false,
        },
        {
            scenario: 'a sibling holding the name',
            candidate: 'Marketing site',
            options: { excludeProjectId: 2 },
            expected: true,
        },
        {
            scenario: 'a sibling holding it in another case',
            candidate: 'MARKETING SITE',
            options: { excludeProjectId: 2 },
            expected: true,
        },
    ])('given $scenario, returns $expected', ({ candidate, options, expected }) => {
        expect(isProjectNameTaken(candidate, projects, options)).toBe(expected)
    })

    describe('a name shared with a sibling from before the rule existed', () => {
        // Organizations still hold projects that share a name. The API accepts a save that leaves
        // such a name alone, so the rename form must not flag it the moment the page loads.
        const duplicates = [project(1, 'Default project'), project(2, 'Default project')]

        test.each([
            { scenario: 'left alone', candidate: 'Default project', expected: false },
            { scenario: 'left alone but padded', candidate: '  Default project  ', expected: false },
            { scenario: 'changed to another taken name', candidate: 'Default project 2', expected: true },
        ])('reports it as $expected when $scenario', ({ candidate, expected }) => {
            const withThirdProject = [...duplicates, project(3, 'Default project 2')]
            expect(
                isProjectNameTaken(candidate, withThirdProject, {
                    excludeProjectId: 1,
                    currentName: 'Default project',
                })
            ).toBe(expected)
        })
    })

    it('treats a missing project list as no collision', () => {
        expect(isProjectNameTaken('Marketing site', undefined)).toBe(false)
    })
})

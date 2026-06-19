import { resolveSkillFile } from './load-skill'

describe('resolveSkillFile', () => {
    it('resolves a companion file relative to the skill folder', () => {
        expect(resolveSkillFile('skills/research/SKILL.md', 'references/deep.md')).toBe(
            'skills/research/references/deep.md'
        )
    })

    it('supports arbitrarily nested companion paths', () => {
        expect(resolveSkillFile('skills/research/SKILL.md', 'assets/templates/email.html')).toBe(
            'skills/research/assets/templates/email.html'
        )
    })

    it('normalizes backslashes to forward slashes', () => {
        expect(resolveSkillFile('skills/research/SKILL.md', 'scripts\\run.py')).toBe('skills/research/scripts/run.py')
    })

    it('rejects absolute paths', () => {
        expect(() => resolveSkillFile('skills/research/SKILL.md', '/etc/passwd')).toThrow(/relative/)
    })

    it('rejects parent traversal', () => {
        expect(() => resolveSkillFile('skills/research/SKILL.md', '../other/SKILL.md')).toThrow(/traversal/)
        expect(() => resolveSkillFile('skills/research/SKILL.md', 'references/../../escape.md')).toThrow(/traversal/)
    })

    it('rejects single-dot segments', () => {
        expect(() => resolveSkillFile('skills/research/SKILL.md', './deep.md')).toThrow(/traversal/)
    })

    it('rejects empty segments', () => {
        expect(() => resolveSkillFile('skills/research/SKILL.md', 'references//deep.md')).toThrow(/traversal/)
    })

    it('rejects companion reads for a legacy flat skill (no own folder)', () => {
        // `skills/research.md`'s dir is the shared `skills/` root — a companion
        // read there could reach a sibling skill, so it must be refused.
        expect(() => resolveSkillFile('skills/research.md', 'other.md')).toThrow(/no companion files/)
        expect(() => resolveSkillFile('skills/research.md', 'sibling/SKILL.md')).toThrow(/no companion files/)
    })
})

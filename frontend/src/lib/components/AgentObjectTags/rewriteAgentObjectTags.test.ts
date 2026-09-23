import { rewriteAgentObjectTags } from './rewriteAgentObjectTags'

const BASE = '/project/2'

describe('rewriteAgentObjectTags', () => {
    it.each([
        [
            'labeled inline tag',
            'See <insight id="9pQx3">checkout funnel</insight>.',
            'See [checkout funnel](/project/2/insights/9pQx3).',
        ],
        [
            'self-closing block tag with a title (the empty-bullet repro)',
            '- <insight id="geFISqzd" display="block" title="Sandbox 2.0 — external chats"/>',
            '- [Sandbox 2.0 — external chats](/project/2/insights/geFISqzd)',
        ],
        [
            'bare-id body written by older notebook tools',
            'See <insight>abc123</insight>.',
            'See [Insight abc123](/project/2/insights/abc123).',
        ],
        ['alias kind', '<recording id="s1">the session</recording>', '[the session](/project/2/replay/s1)'],
        [
            'flag cited by numeric id links, by key stays a label',
            '<flag id="42">new-flow</flag> vs <flag id="my-key">old-flow</flag>',
            '[new-flow](/project/2/feature_flags/42) vs old-flow',
        ],
        [
            'inline hogql links into the SQL editor',
            'See <hogql label="signups today">SELECT count() FROM events</hogql>.',
            'See [signups today](/project/2/sql?open_query=SELECT%20count%28%29%20FROM%20events).',
        ],
        [
            'unknown kind keeps the label and drops the markup',
            'From <inbox id="r1">the report</inbox>.',
            'From the report.',
        ],
        [
            'label unsafe for a markdown link is sanitized',
            '<insight id="a">Error [rate] > 1% | daily</insight>',
            '[Error rate &gt; 1% daily](/project/2/insights/a)',
        ],
    ])('%s', (_name, input, expected) => {
        expect(rewriteAgentObjectTags(input, BASE)).toBe(expected)
    })

    it('renders a block hogql tag as a linked title over a fence with its caption', () => {
        const input = 'Numbers:\n<hogql display="block" title="DAU" caption="last 7 days">SELECT 1</hogql>\nDone.'
        expect(rewriteAgentObjectTags(input, BASE)).toBe(
            'Numbers:\n\n**[DAU](/project/2/sql?open_query=SELECT%201)**\n```\nSELECT 1\n```\n_last 7 days_\n\nDone.'
        )
    })

    it.each([
        ['inline code', 'Use `<insight id="a">kept</insight>`.'],
        ['fenced code', '```xml\n<insight id="a">kept</insight>\n```'],
        ['plain text without tags', 'Nothing to do here.'],
        ['unknown non-object markup', 'A <div>block</div> stays.'],
        ['an unclosed fence containing a tag', 'Before\n```\n<insight id="a">x</insight>'],
        ['a trailing opener inside inline code', 'Use `<insight id="a">`'],
        ['a trailing partial that matches no kind', 'plain <widget'],
        ['a comparison that looks like a partial tag', 'value a<b'],
    ])('leaves %s untouched', (_name, input) => {
        expect(rewriteAgentObjectTags(input, BASE)).toBe(input)
    })

    it.each([
        ['a partial opener of a known kind', 'Streaming <insi', 'Streaming '],
        ['a complete opener whose closer has not arrived', 'Streaming <insight id="a">Runtime', 'Streaming '],
        ['an unregistered opener carrying an id', 'From <inbox id="r1">the rep', 'From '],
    ])('holds back %s until the rest of the chunk arrives', (_name, input, expected) => {
        expect(rewriteAgentObjectTags(input, BASE)).toBe(expected)
    })

    it('does not split a complete hogql tag whose SQL quotes tag markup', () => {
        expect(rewriteAgentObjectTags('See <hogql label="q">SELECT \'<insight id="x">\'</hogql>.', BASE)).toBe(
            'See [q](/project/2/sql?open_query=SELECT%20%27%3Cinsight%20id%3D%22x%22%3E%27).'
        )
    })

    it('grows the fence past any backtick run in the SQL', () => {
        expect(rewriteAgentObjectTags('<hogql display="block" title="T">a\n```\nb</hogql>', BASE)).toBe(
            '**[T](/project/2/sql?open_query=a%0A%60%60%60%0Ab)**\n````\na\n```\nb\n````'
        )
    })

    it('keeps markdown link syntax in a caption inert', () => {
        expect(
            rewriteAgentObjectTags(
                '<hogql display="block" title="T" caption="![x](https://evil.test/p)">SELECT 1</hogql>',
                BASE
            )
        ).toBe('**[T](/project/2/sql?open_query=SELECT%201)**\n```\nSELECT 1\n```\n_! x (https://evil.test/p)_')
    })

    it('drops a list marker whose only content is a promoted block', () => {
        expect(rewriteAgentObjectTags('- <hogql display="block" title="T">SELECT 1</hogql>', BASE)).toBe(
            '**[T](/project/2/sql?open_query=SELECT%201)**\n```\nSELECT 1\n```'
        )
    })

    it('is idempotent over its own output', () => {
        const once = rewriteAgentObjectTags('- <insight id="a" display="block" title="T"/>', BASE)
        expect(rewriteAgentObjectTags(once, BASE)).toBe(once)
    })

    it('links project-relative when no project base is known', () => {
        expect(rewriteAgentObjectTags('<insight id="a">x</insight>', '')).toBe('[x](/insights/a)')
    })
})

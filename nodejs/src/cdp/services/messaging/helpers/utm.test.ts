import { addUtmTagsToEmail, resolveUtmTags } from './utm'

const TAGS = { utm_source: 'posthog', utm_medium: 'email', utm_campaign: 'Spring sale', utm_content: '' }
const SITE_URL = 'https://us.posthog.com'
const QUERY = 'utm_source=posthog&amp;utm_medium=email&amp;utm_campaign=Spring%20sale'

describe('addUtmTagsToEmail', () => {
    it.each([
        {
            case: 'a plain link',
            html: '<a href="https://example.com/pricing">x</a>',
            expected: `<a href="https://example.com/pricing?${QUERY}">x</a>`,
        },
        {
            case: 'a link with a query and a fragment',
            html: '<a href="https://example.com/p?a=1&amp;b=2#plans">x</a>',
            expected: `<a href="https://example.com/p?a=1&amp;b=2&amp;${QUERY}#plans">x</a>`,
        },
        {
            case: 'a link that already sets its campaign',
            html: "<a class='btn' href='https://example.com/?utm_campaign=launch'>x</a>",
            expected:
                "<a class='btn' href='https://example.com/?utm_campaign=launch&amp;utm_source=posthog&amp;utm_medium=email'>x</a>",
        },
        {
            case: 'a link that already has every tag',
            html: '<a href="https://example.com/?utm_source=a&utm_medium=b&utm_campaign=c">x</a>',
            expected: '<a href="https://example.com/?utm_source=a&utm_medium=b&utm_campaign=c">x</a>',
        },
        {
            case: 'the unsubscribe link on the PostHog host',
            html: '<a href="https://us.posthog.com/messaging-preferences/abc/">Unsubscribe</a>',
            expected: '<a href="https://us.posthog.com/messaging-preferences/abc/">Unsubscribe</a>',
        },
        {
            case: 'mailto, relative and anchor links',
            html: '<a href="mailto:hi@example.com">m</a><a href="/docs">r</a><a href="#top">a</a>',
            expected: '<a href="mailto:hi@example.com">m</a><a href="/docs">r</a><a href="#top">a</a>',
        },
        {
            case: 'a link marked data-ph-no-utm',
            html: '<a data-ph-no-utm href="https://example.com/pricing">x</a>',
            expected: '<a data-ph-no-utm href="https://example.com/pricing">x</a>',
        },
        {
            case: 'a link with data-href before href',
            html: '<a data-href="x" href="https://example.com/pricing">x</a>',
            expected: `<a data-href="x" href="https://example.com/pricing?${QUERY}">x</a>`,
        },
        {
            case: 'a link whose title mentions data-ph-no-utm',
            html: '<a title="add data-ph-no-utm to skip" href="https://example.com/pricing">x</a>',
            expected: `<a title="add data-ph-no-utm to skip" href="https://example.com/pricing?${QUERY}">x</a>`,
        },
        {
            case: 'an <abbr> next to a link',
            html: '<abbr title="x">PH</abbr><a href="https://example.com/pricing">x</a>',
            expected: `<abbr title="x">PH</abbr><a href="https://example.com/pricing?${QUERY}">x</a>`,
        },
        {
            case: 'a quoted > inside the tag',
            html: '<a title="a > b" href="https://example.com/pricing">x</a>',
            expected: `<a title="a > b" href="https://example.com/pricing?${QUERY}">x</a>`,
        },
        {
            case: 'an unclosed tag after a link',
            html: '<a href="https://example.com/pricing">x</a> <a <a <a',
            expected: `<a href="https://example.com/pricing?${QUERY}">x</a> <a <a <a`,
        },
        {
            case: 'an unrendered template tag',
            html: '<a href="https://example.com/{{ person.id }}">x</a>',
            expected: '<a href="https://example.com/{{ person.id }}">x</a>',
        },
    ])('tags $case', ({ html, expected }) => {
        expect(addUtmTagsToEmail(html, TAGS, SITE_URL)).toEqual(expected)
    })

    it.each([
        {
            case: 'no custom values',
            rendered: undefined,
            expected: { utm_campaign: 'Spring sale', utm_content: 'Send email' },
        },
        {
            case: 'a custom campaign and content',
            rendered: { utm_campaign: 'pro-plan', utm_content: ' hero ' },
            expected: { utm_campaign: 'pro-plan', utm_content: 'hero' },
        },
        {
            case: 'a value that rendered empty',
            rendered: { utm_campaign: '  ' },
            expected: { utm_campaign: 'Spring sale' },
        },
    ])('resolves the tags from $case', ({ rendered, expected }) => {
        expect(resolveUtmTags({ ...TAGS, utm_content: 'Send email' }, rendered)).toMatchObject({
            utm_source: 'posthog',
            ...expected,
        })
    })
})

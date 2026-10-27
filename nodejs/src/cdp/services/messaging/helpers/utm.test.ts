import { addUtmTagsToEmail, addWorkflowRunTagToEmail, resolveUtmTags } from './utm'

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

    it.each([
        {
            case: 'tags a link on the sender domain',
            html: '<a href="https://example.com/p?a=1#plans">x</a>',
            expected: '<a href="https://example.com/p?a=1&amp;ph_workflow_run=run-1#plans">x</a>',
        },
        {
            case: 'tags a link on another subdomain of the sender domain',
            html: '<a href="https://app.example.com/">x</a>',
            expected: '<a href="https://app.example.com/?ph_workflow_run=run-1">x</a>',
        },
        {
            case: 'keeps the UTM tags already on a link',
            html: `<a href="https://example.com/?${QUERY}">x</a>`,
            expected: `<a href="https://example.com/?${QUERY}&amp;ph_workflow_run=run-1">x</a>`,
        },
        {
            case: 'leaves links off the sender domain, signed or lookalike',
            html: '<a href="https://other.com/">x</a><a href="https://bucket.s3.amazonaws.com/f.pdf?X-Amz-Signature=abc">y</a><a href="https://example.com.evil.io/">z</a>',
            expected:
                '<a href="https://other.com/">x</a><a href="https://bucket.s3.amazonaws.com/f.pdf?X-Amz-Signature=abc">y</a><a href="https://example.com.evil.io/">z</a>',
        },
        {
            case: 'leaves another app on the shared hosting domain of the sender',
            sender: 'hi@acme.herokuapp.com',
            html: '<a href="https://other.herokuapp.com/">x</a>',
            expected: '<a href="https://other.herokuapp.com/">x</a>',
        },
        {
            case: 'leaves the unsubscribe link on the PostHog host',
            sender: 'hi@posthog.com',
            html: '<a href="https://us.posthog.com/messaging-preferences/abc/">Unsubscribe</a>',
            expected: '<a href="https://us.posthog.com/messaging-preferences/abc/">Unsubscribe</a>',
        },
        {
            case: 'leaves mailto, tel, javascript, relative and anchor links',
            html: '<a href="mailto:hi@example.com">m</a><a href="tel:+15550100">t</a><a href="javascript:void(0)">j</a><a href="/docs">r</a><a href="#top">a</a>',
            expected:
                '<a href="mailto:hi@example.com">m</a><a href="tel:+15550100">t</a><a href="javascript:void(0)">j</a><a href="/docs">r</a><a href="#top">a</a>',
        },
        {
            case: 'leaves malformed and unrendered links',
            html: '<a href="https://">a</a><a href="https://exa mple.com/">b</a><a href="https://example.com/{{ person.id }}">c</a><a href>d</a>',
            expected:
                '<a href="https://">a</a><a href="https://exa mple.com/">b</a><a href="https://example.com/{{ person.id }}">c</a><a href>d</a>',
        },
        {
            case: 'leaves an email without links',
            html: '<p>Your <abbr>PDF</abbr> is attached.</p>',
            expected: '<p>Your <abbr>PDF</abbr> is attached.</p>',
        },
        {
            case: 'leaves a link opted out of click tracking',
            html: '<a clicktracking="off" href="https://example.com/">x</a><a data-ph-no-track href="https://example.com/">y</a>',
            expected:
                '<a clicktracking="off" href="https://example.com/">x</a><a data-ph-no-track href="https://example.com/">y</a>',
        },
        {
            case: 'leaves a link SES never tracks',
            html: '<a ses:no-track href="https://example.com/">x</a>',
            expected: '<a ses:no-track href="https://example.com/">x</a>',
        },
        {
            case: 'replaces the run id of an earlier send',
            html: '<a href="https://example.com/p?ph_workflow_run=old-run&amp;a=1">x</a>',
            expected: '<a href="https://example.com/p?a=1&amp;ph_workflow_run=run-1">x</a>',
        },
        {
            case: 'replaces every run id of earlier sends and keeps a hash route',
            html: '<a href="https://example.com/?ph_workflow_run=a&amp;ph_workflow_run=b#/p?ph_workflow_run=x">x</a>',
            expected: '<a href="https://example.com/?ph_workflow_run=run-1#/p?ph_workflow_run=x">x</a>',
        },
        {
            case: 'tags a link that only opts out of UTM tags',
            html: '<a data-ph-no-utm href="https://example.com/">x</a>',
            expected: '<a data-ph-no-utm href="https://example.com/?ph_workflow_run=run-1">x</a>',
        },
    ])('$case', ({ html, expected, sender }) => {
        expect(
            addWorkflowRunTagToEmail(html, {
                runId: 'run-1',
                senderEmail: sender ?? 'hi@mail.example.com',
                siteUrl: SITE_URL,
            })
        ).toEqual(expected)
    })
})

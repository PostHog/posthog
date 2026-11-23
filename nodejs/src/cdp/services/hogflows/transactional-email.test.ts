import { HogFlowAction } from '~/cdp/schema/hogflow'

import { marketingSendRefusal } from './transactional-email'

const marketingCategory = { id: '00000000-0000-0000-0000-000000000001', type: 'marketing' as const }

const emailActionWithHtml = (html: string): HogFlowAction => ({
    id: 'email_1',
    name: 'Email',
    description: '',
    type: 'function_email',
    created_at: 0,
    updated_at: 0,
    filters: {},
    config: {
        template_id: 'template-email',
        message_category_type: 'marketing',
        inputs: {
            email: {
                value: {
                    subject: 'News',
                    html,
                    text: '',
                },
            },
        },
    },
})

describe('marketingSendRefusal', () => {
    it.each([
        [
            'an if conditional around unsubscribe_url',
            '<a href="{% if true %}{{ unsubscribe_url }}{% endif %}">Unsubscribe</a>',
            undefined,
        ],
        [
            'whitespace-trimmed if/else branches',
            '<a href="{%- if variables.lang == \'de\' -%}{{ unsubscribe_url }}?lang=de{%- else -%}{{ unsubscribe_url }}{%- endif -%}">Unsubscribe</a>',
            undefined,
        ],
        [
            'an unless/else conditional with unsubscribe_url in the fallback branch',
            '<a href="{% unless variables.skip %}https://example.com{% else %}{{ unsubscribe_url }}{% endunless %}">Unsubscribe</a>',
            undefined,
        ],
        [
            'a case/when conditional',
            '<a href="{% case variables.kind %}{% when \'one\' %}{{ unsubscribe_url_one_click }}{% else %}{{ unsubscribe_url }}{% endcase %}">Unsubscribe</a>',
            undefined,
        ],
        [
            'nested if conditionals around unsubscribe_url',
            '<a href="{% if a %}{% if b %}{{ unsubscribe_url }}{% endif %}{% endif %}">Unsubscribe</a>',
            undefined,
        ],
        [
            'a conditional followed by a query string',
            '<a href="{% if true %}{{ unsubscribe_url }}{% endif %}?utm_source=email">Unsubscribe</a>',
            undefined,
        ],
        [
            'an optional conditional query string after unsubscribe_url',
            '<a href="{{ unsubscribe_url }}{% if variables.lang %}?lang={{ variables.lang }}{% endif %}">Unsubscribe</a>',
            undefined,
        ],
        [
            'an if/else conditional query string after unsubscribe_url',
            '<a href="{{ unsubscribe_url }}{% if variables.a %}?a=1{% else %}?a=2{% endif %}">Unsubscribe</a>',
            undefined,
        ],
        [
            'a conditional query parameter appended after a query string',
            '<a href="{{ unsubscribe_url }}?a=1{% if variables.b %}&b=2{% endif %}">Unsubscribe</a>',
            undefined,
        ],
        [
            'an optional conditional fragment after unsubscribe_url',
            '<a href="{{ unsubscribe_url }}{% if variables.frag %}#footer{% endif %}">Unsubscribe</a>',
            undefined,
        ],
        [
            'an exhaustive conditional query string followed by an optional conditional query parameter',
            '<a href="{{ unsubscribe_url }}{% if variables.a %}?a=1{% else %}?a=2{% endif %}{% if variables.b %}&b=2{% endif %}">Unsubscribe</a>',
            undefined,
        ],
        [
            'a nested conditional query parameter inside a conditional query string',
            '<a href="{{ unsubscribe_url }}{% if variables.a %}?a=1{% if variables.b %}&b=2{% endif %}{% endif %}">Unsubscribe</a>',
            undefined,
        ],
        [
            'a case conditional query string after unsubscribe_url',
            "<a href=\"{{ unsubscribe_url }}{% case variables.lang %}{% when 'de' %}?lang=de{% when 'fr' %}?lang=fr{% endcase %}\">Unsubscribe</a>",
            undefined,
        ],
        [
            'an optional conditional query string nested inside a conditional unsubscribe_url branch',
            '<a href="{% if variables.a %}{{ unsubscribe_url }}{% if variables.lang %}?lang={{ variables.lang }}{% endif %}{% endif %}">Unsubscribe</a>',
            undefined,
        ],
        [
            'a foreign-host URL wrapping an if conditional',
            '<a href="https://example.com/?next={% if true %}{{ unsubscribe_url }}{% endif %}">Unsubscribe</a>',
            'unsubscribe_link_required',
        ],
        [
            'a foreign-host URL inside an if branch',
            '<a href="{% if true %}https://example.com/?next={{ unsubscribe_url }}{% endif %}">Unsubscribe</a>',
            'unsubscribe_link_required',
        ],
        [
            'a foreign-host prefix before a nested if branch',
            '<a href="{% if a %}https://example.com/?next={% if b %}{{ unsubscribe_url }}{% endif %}{% endif %}">Unsubscribe</a>',
            'unsubscribe_link_required',
        ],
        [
            'a conditional prefix preceding unsubscribe_url at top level',
            '<a href="{% if true %}https://example.com/?next={% endif %}{{ unsubscribe_url }}">Unsubscribe</a>',
            'unsubscribe_link_required',
        ],
        [
            'a conditional prefix preceding a conditional unsubscribe_url',
            '<a href="{% if a %}https://example.com/?next={% endif %}{% if b %}{{ unsubscribe_url }}{% endif %}">Unsubscribe</a>',
            'unsubscribe_link_required',
        ],
        [
            'a conditional suffix after a conditional unsubscribe_url',
            '<a href="{% if a %}{{ unsubscribe_url }}{% endif %}{% if b %}.example.com{% endif %}">Unsubscribe</a>',
            'unsubscribe_link_required',
        ],
        [
            'a nested conditional followed by a sibling conditional',
            '<a href="{% if a %}{% if b %}{{ unsubscribe_url }}{% endif %}{% if c %}.example.com{% endif %}{% endif %}">Unsubscribe</a>',
            'unsubscribe_link_required',
        ],
        [
            'unsubscribe_url placed before the first when clause in a case block',
            '<a href="{% case mode %}{{ unsubscribe_url }}{% when \'a\' %}https://example.com{% endcase %}">Unsubscribe</a>',
            'unsubscribe_link_required',
        ],
        [
            'a duplicate else clause',
            '<a href="{% if a %}{{ unsubscribe_url }}{% else %}https://example.com{% else %}https://example.org{% endif %}">Unsubscribe</a>',
            'unsubscribe_link_required',
        ],
        [
            'a conditional followed by non-query text',
            '<a href="{% if true %}{{ unsubscribe_url }}{% endif %}extra">Unsubscribe</a>',
            'unsubscribe_link_required',
        ],
        [
            'an unclosed if conditional',
            '<a href="{% if true %}{{ unsubscribe_url }}">Unsubscribe</a>',
            'unsubscribe_link_required',
        ],
        [
            'a conditional domain suffix after unsubscribe_url',
            '<a href="{{ unsubscribe_url }}{% if true %}.evil.com{% endif %}">Unsubscribe</a>',
            'unsubscribe_link_required',
        ],
        [
            'a conditional path traversal suffix after unsubscribe_url',
            '<a href="{{ unsubscribe_url }}{% if true %}/../other{% endif %}">Unsubscribe</a>',
            'unsubscribe_link_required',
        ],
        [
            'a conditional authority suffix after unsubscribe_url',
            '<a href="{{ unsubscribe_url }}{% if true %}@evil.com{% endif %}">Unsubscribe</a>',
            'unsubscribe_link_required',
        ],
        [
            'a conditional raw variable suffix before any query or fragment',
            '<a href="{{ unsubscribe_url }}{% if true %}{{ variables.path }}{% endif %}">Unsubscribe</a>',
            'unsubscribe_link_required',
        ],
        [
            'a conditional suffix whose else branch appends path text',
            '<a href="{{ unsubscribe_url }}{% if true %}?a=1{% else %}/evil{% endif %}">Unsubscribe</a>',
            'unsubscribe_link_required',
        ],
        [
            'an optional query conditional followed by a bare ampersand suffix',
            '<a href="{{ unsubscribe_url }}{% if variables.a %}?a=1{% endif %}&b=2">Unsubscribe</a>',
            'unsubscribe_link_required',
        ],
        [
            'an optional query conditional followed by a second conditional starting with an ampersand',
            '<a href="{{ unsubscribe_url }}{% if variables.a %}?a=1{% endif %}{% if variables.b %}&b=2{% endif %}">Unsubscribe</a>',
            'unsubscribe_link_required',
        ],
        [
            'an elsif suffix with an empty branch followed by a bare ampersand suffix',
            '<a href="{{ unsubscribe_url }}{% if variables.a %}?a=1{% elsif variables.b %}{% else %}?c=3{% endif %}&d=4">Unsubscribe</a>',
            'unsubscribe_link_required',
        ],
        [
            'an unclosed suffix conditional after unsubscribe_url',
            '<a href="{{ unsubscribe_url }}{% if true %}?a=1">Unsubscribe</a>',
            'unsubscribe_link_required',
        ],
        [
            'a duplicate else clause in a suffix conditional after unsubscribe_url',
            '<a href="{{ unsubscribe_url }}{% if true %}?a=1{% else %}?a=2{% else %}?a=3{% endif %}">Unsubscribe</a>',
            'unsubscribe_link_required',
        ],
    ])('evaluates a saved email step with %s', (_name, html, expected) => {
        expect(marketingSendRefusal(emailActionWithHtml(html), undefined, marketingCategory)).toEqual(expected)
    })
})

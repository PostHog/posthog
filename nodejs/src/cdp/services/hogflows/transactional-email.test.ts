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
    ])('evaluates a saved email step with %s', (_name, html, expected) => {
        expect(marketingSendRefusal(emailActionWithHtml(html), undefined, marketingCategory)).toEqual(expected)
    })
})

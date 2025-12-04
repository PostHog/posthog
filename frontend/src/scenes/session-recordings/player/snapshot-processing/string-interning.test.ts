import { createStringInterner, internedReviver } from './string-interning'

function generateSnapshotData(eventCount: number): string[] {
    const events: string[] = []
    // Use longer strings that V8 won't automatically intern
    const cssRules = [
        '.container-main-wrapper-element { display: flex; align-items: center; justify-content: space-between; }',
        '.sidebar-navigation-list-item { padding: 16px 24px; margin: 8px 0; border-radius: 4px; }',
        '.content-section-header-title { font-size: 24px; font-weight: 600; line-height: 1.4; }',
        '.button-primary-action-submit { background-color: #1890ff; color: white; border: none; }',
        '.form-input-field-wrapper { position: relative; width: 100%; max-width: 400px; }',
    ]
    const urls = [
        'https://example.com/dashboard/analytics/reports/monthly-summary?period=last-30-days',
        'https://example.com/settings/organization/team-members/permissions?role=admin',
        'https://example.com/projects/frontend-redesign/tasks/in-progress?assignee=current',
    ]

    for (let i = 0; i < eventCount; i++) {
        events.push(
            JSON.stringify({
                type: 2,
                timestamp: 1700000000000 + i,
                data: {
                    href: urls[i % urls.length],
                    node: {
                        type: 2,
                        attributes: {
                            style: cssRules[i % cssRules.length],
                            'data-url': urls[i % urls.length],
                        },
                        childNodes: [
                            { type: 2, attributes: { style: cssRules[(i + 1) % cssRules.length] } },
                            { type: 2, attributes: { style: cssRules[(i + 2) % cssRules.length] } },
                        ],
                    },
                },
            })
        )
    }
    return events
}

function collectStringReferences(obj: unknown, refs: string[] = []): string[] {
    if (typeof obj === 'string') {
        refs.push(obj)
    } else if (Array.isArray(obj)) {
        obj.forEach((item) => collectStringReferences(item, refs))
    } else if (obj && typeof obj === 'object') {
        Object.values(obj).forEach((value) => collectStringReferences(value, refs))
    }
    return refs
}

function countUniqueReferences(strings: string[]): number {
    const seen = new Map<string, string>()
    let uniqueCount = 0
    for (const s of strings) {
        const existing = seen.get(s)
        if (existing === undefined || !Object.is(existing, s)) {
            seen.set(s, s)
            uniqueCount++
        }
    }
    return uniqueCount
}

describe('string interning', () => {
    describe('createStringInterner', () => {
        it('returns same reference for repeated strings', () => {
            const intern = createStringInterner()
            const strings = ['type', 'data', 'id', 'type', 'data', 'id', 'type']
            const results = strings.map((s) => intern(s))

            expect(Object.is(results[0], results[3])).toBe(true)
            expect(Object.is(results[0], results[6])).toBe(true)
            expect(Object.is(results[1], results[4])).toBe(true)
            expect(Object.is(results[2], results[5])).toBe(true)
        })

        it('returns different references for different strings', () => {
            const intern = createStringInterner()
            expect(Object.is(intern('hello'), intern('world'))).toBe(false)
        })
    })

    describe('internedReviver', () => {
        it('interns strings during JSON.parse', () => {
            const intern = createStringInterner()
            const parsed = JSON.parse('{"type":"event","data":{"type":"event"}}', internedReviver(intern)) as {
                type: string
                data: { type: string }
            }

            expect(Object.is(parsed.type, parsed.data.type)).toBe(true)
        })

        it.each([
            ['numbers', '{"count":42}', { count: 42 }],
            ['booleans', '{"flag":true}', { flag: true }],
            ['null', '{"value":null}', { value: null }],
            ['nested objects', '{"a":{"b":"c"}}', { a: { b: 'c' } }],
        ])('preserves %s', (_name, json, expected) => {
            const intern = createStringInterner()
            expect(JSON.parse(json, internedReviver(intern))).toEqual(expected)
        })

        it('interns repeated strings in snapshot-like structures', () => {
            const intern = createStringInterner()
            const parsed = JSON.parse(
                JSON.stringify({
                    data: {
                        node: {
                            tagName: 'div',
                            attributes: { class: 'container' },
                            childNodes: [
                                { tagName: 'div', attributes: { class: 'container' } },
                                { tagName: 'span', attributes: { class: 'container' } },
                            ],
                        },
                    },
                }),
                internedReviver(intern)
            ) as {
                data: {
                    node: {
                        tagName: string
                        attributes: { class: string }
                        childNodes: Array<{ tagName: string; attributes: { class: string } }>
                    }
                }
            }

            const root = parsed.data.node
            const [first, second] = root.childNodes

            expect(Object.is(root.tagName, first.tagName)).toBe(true)
            expect(Object.is(root.attributes.class, first.attributes.class)).toBe(true)
            expect(Object.is(first.attributes.class, second.attributes.class)).toBe(true)
        })
    })

    describe('memory efficiency', () => {
        it('interned strings share references across parsed objects', () => {
            const events = generateSnapshotData(100)
            const intern = createStringInterner()
            const reviver = internedReviver(intern)

            const parsed = events.map((e) => JSON.parse(e, reviver))

            // Collect all string references
            const refs: string[] = []
            parsed.forEach((obj) => collectStringReferences(obj, refs))

            // Count how many are unique references vs total
            const uniqueRefs = countUniqueReferences(refs)
            const totalRefs = refs.length

            // With 100 events using 5 CSS rules and 3 URLs repeated,
            // we should have far fewer unique references than total
            // Each event has ~5 string values, so ~500 total refs
            // But only 8 unique string values (5 CSS + 3 URLs)
            expect(uniqueRefs).toBeLessThan(totalRefs / 10)
        })
    })
})

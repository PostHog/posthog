import {
    isStartOfMacroSlash,
    macroContextFromTicket,
    macroPreview,
    renderMacro,
    type MacroContext,
} from './renderMacro'

const ctx: MacroContext = {
    customer: { first_name: 'Jane', name: 'Jane Doe', email: 'jane@example.com' },
    agent: { first_name: 'Nik', name: 'Nik Smith' },
    ticket: { number: '42' },
}

describe('support macros', () => {
    test.each<[string, MacroContext, string]>([
        ['Hi {{customer.first_name}}, ticket {{ticket.number}}', ctx, 'Hi Jane, ticket 42'],
        ['Cheers,\n{{agent.first_name}}', ctx, 'Cheers,\nNik'],
        ['{{ customer.name }} <{{customer.email}}>', ctx, 'Jane Doe <jane@example.com>'],
        ['From {{agent.name}}', ctx, 'From Nik Smith'],
        [
            'Hi {{customer.first_name}}',
            { ...ctx, customer: { first_name: null, name: null, email: 'jane@example.com' } },
            'Hi {{customer.first_name}}',
        ],
        ['See {{customer.plan}}', ctx, 'See {{customer.plan}}'],
        ['No vars', ctx, 'No vars'],
        ['Hi \\{\\{customer\\.first\\_name\\}\\}, \\{\\{ticket\\.number\\}\\}', ctx, 'Hi Jane, 42'],
        ["What's up\\! {{customer.first_name}}", ctx, "What's up\\! Jane"],
    ])('renders %s', (body, context, expected) => {
        expect(renderMacro(body, context)).toBe(expected)
    })

    it('does not treat an email address as a first name', () => {
        const context = macroContextFromTicket(
            {
                ticket_number: 7,
                anonymous_traits: { email: 'jane@example.com' },
                person: null,
            } as unknown as Parameters<typeof macroContextFromTicket>[0],
            { first_name: 'Nik', email: 'nik@example.com' } as unknown as Parameters<typeof macroContextFromTicket>[1]
        )
        expect(context.customer.first_name).toBeNull()
        expect(context.customer.name).toBe('jane@example.com')
        expect(context.customer.email).toBe('jane@example.com')
        expect(context.agent.first_name).toBe('Nik')
        expect(context.ticket.number).toBe('7')
    })

    it('uses the first non-empty line and truncates it', () => {
        const body = `\n\n${'Thanks for writing. '.repeat(10)}`
        expect(macroPreview(body).endsWith('…')).toBe(true)
        expect(macroPreview(body).length).toBe(80)
        expect(macroPreview('Hi \\{\\{customer\\.name\\}\\}\\!')).toBe('Hi {{customer.name}}!')
    })

    test.each([
        ['', true],
        [' ', true],
        ['\n', true],
        ['/', false],
        ['a', false],
    ])('slash after %j is a trigger: %s', (before, expected) => {
        expect(isStartOfMacroSlash(before)).toBe(expected)
    })
})

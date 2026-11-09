import {
    EmailRecipients,
    SuppressedRecipientsResult,
    fieldsWithControlCharacters,
    removeSuppressedRecipients,
} from './suppressed-recipients'

describe('removeSuppressedRecipients', () => {
    const suppressed = new Set(['bounced@example.com', 'bounced-2@example.com'])
    const isSuppressed = (email: string): Promise<boolean> => Promise.resolve(suppressed.has(email))

    it.each<[string, EmailRecipients, SuppressedRecipientsResult]>([
        [
            'leaves the recipients unchanged when nobody is suppressed',
            { to: { email: 'a@example.com' }, cc: 'b@example.com', bcc: 'c@example.com' },
            { skip: false, cc: 'b@example.com', bcc: 'c@example.com', removed: [] },
        ],
        [
            'removes suppressed cc and bcc entries and keeps the original form of the others',
            {
                to: { email: 'a@example.com' },
                cc: '"B" <b@example.com>, "Gone" <bounced@example.com>',
                bcc: 'bounced-2@example.com',
            },
            {
                skip: false,
                cc: '"B" <b@example.com>',
                bcc: '',
                removed: ['bounced@example.com', 'bounced-2@example.com'],
            },
        ],
        [
            'removes a suppressed bracketed address that has text after it',
            { to: { email: 'a@example.com' }, cc: '"Gone" <bounced@example.com> (old), b@example.com' },
            { skip: false, cc: 'b@example.com', bcc: '', removed: ['bounced@example.com'] },
        ],
        [
            'checks the mailbox, not an address inside a quoted display name',
            {
                to: { email: 'a@example.com' },
                cc: '"Bob <ok@example.com>" <bounced@example.com>, "Doe, Jane" <j@example.com>',
            },
            { skip: false, cc: '"Doe Jane" <j@example.com>', bcc: '', removed: ['bounced@example.com'] },
        ],
        [
            'checks a quoted local part unquoted and keeps the quotes for delivery',
            { to: { email: 'a@example.com' }, cc: '"bounced"@example.com, "john doe"@example.com' },
            { skip: false, cc: '"john doe"@example.com', bcc: '', removed: ['bounced@example.com'] },
        ],
        [
            'checks a quoted to address unquoted',
            { to: { email: '"bounced"@example.com' }, cc: 'b@example.com' },
            {
                skip: false,
                promotedTo: { email: 'b@example.com' },
                cc: '',
                bcc: '',
                removed: ['bounced@example.com'],
            },
        ],
        [
            'promotes the first deliverable cc address when to is suppressed',
            {
                to: { email: 'bounced@example.com' },
                cc: 'bounced-2@example.com, "Admin B" <b@example.com>, c@example.com',
            },
            {
                skip: false,
                promotedTo: { email: 'b@example.com', name: 'Admin B' },
                cc: 'c@example.com',
                bcc: '',
                removed: ['bounced@example.com', 'bounced-2@example.com'],
            },
        ],
        [
            'skips when to is suppressed and only bcc addresses are left',
            { to: { email: 'bounced@example.com' }, bcc: 'hidden@example.com' },
            { skip: true, removed: ['bounced@example.com'] },
        ],
        [
            'does not skip when there is no to address to check',
            { to: { email: '' }, cc: 'b@example.com' },
            { skip: false, cc: 'b@example.com', bcc: undefined, removed: [] },
        ],
    ])('%s', async (_name, recipients, expected) => {
        expect(await removeSuppressedRecipients(recipients, isSuppressed)).toEqual(expected)
    })
})

describe('fieldsWithControlCharacters', () => {
    it.each<[string, EmailRecipients, string[]]>([
        [
            'a null character in the To address',
            { to: { email: 'jo\u0000@example.com' } },
            ['To "jo\\u0000@example.com"'],
        ],
        ['U+0001 in the To address', { to: { email: 'jo\u0001@example.com' } }, ['To "jo\\u0001@example.com"']],
        ['backspace in the To address', { to: { email: 'jo\b@example.com' } }, ['To "jo\\u0008@example.com"']],
        ['vertical tab in the To address', { to: { email: 'jo\v@example.com' } }, ['To "jo\\u000b@example.com"']],
        ['form feed in the To address', { to: { email: 'jo\f@example.com' } }, ['To "jo\\u000c@example.com"']],
        ['U+000E in the To address', { to: { email: 'jo\u000E@example.com' } }, ['To "jo\\u000e@example.com"']],
        ['U+001F in the To address', { to: { email: 'jo\u001F@example.com' } }, ['To "jo\\u001f@example.com"']],
        ['DEL in the To address', { to: { email: 'jo\u007F@example.com' } }, ['To "jo\\u007f@example.com"']],
        [
            'a control character in the To domain',
            { to: { email: 'jo@exa\u0001mple.com' } },
            ['To "jo@exa\\u0001mple.com"'],
        ],
        ['a bare CC address', { cc: 'jo\u0000@example.com' }, ['CC "jo\\u0000@example.com"']],
        [
            'a CC address in angle brackets',
            { cc: '"Jo" <jo\u0001@example.com>' },
            ['CC ""Jo" <jo\\u0001@example.com>"'],
        ],
        ['a quoted CC local part', { cc: '"jo\u0001"@example.com' }, ['CC ""jo\\u0001"@example.com"']],
        [
            'the second entry of a comma list',
            { cc: 'ok@example.com, jo\u0002@example.com' },
            ['CC "ok@example.com, jo\\u0002@example.com"'],
        ],
        [
            'the second entry of a semicolon list',
            { cc: 'ok@example.com; jo\u0002@example.com' },
            ['CC "ok@example.com; jo\\u0002@example.com"'],
        ],
        [
            'a member of a group',
            { cc: 'Team: ok@example.com, jo\u0003@example.com;' },
            ['CC "Team: ok@example.com, jo\\u0003@example.com;"'],
        ],
        ['DEL in a CC address', { cc: 'jo\u007F@example.com' }, ['CC "jo\\u007f@example.com"']],
        [
            'a BCC address',
            { bcc: 'ok@example.com, jo\u0000@example.com' },
            ['BCC "ok@example.com, jo\\u0000@example.com"'],
        ],
        [
            'two CC addresses',
            { cc: 'a\u0001@example.com, b\u0002@example.com' },
            ['CC "a\\u0001@example.com, b\\u0002@example.com"'],
        ],
        ['a trailing control character', { cc: 'jo@example.com\u0000' }, ['CC "jo@example.com\\u0000"']],
        ['a quoted CC display name', { cc: '"Jo\u0001" <jo@example.com>' }, ['CC ""Jo\\u0001" <jo@example.com>"']],
        ['an unquoted CC display name', { cc: 'Jo\u0001 <jo@example.com>' }, ['CC "Jo\\u0001 <jo@example.com>"']],
        ['a CC comment', { cc: 'jo@example.com (Jo\u0001)' }, ['CC "jo@example.com (Jo\\u0001)"']],
        ['DEL in a BCC display name', { bcc: '"Jo\u007F" <jo@example.com>' }, ['BCC ""Jo\\u007f" <jo@example.com>"']],
        ['a group name', { cc: 'Team\u0001: jo@example.com;' }, ['CC "Team\\u0001: jo@example.com;"']],
        [
            'To, CC and BCC together',
            { to: { email: 'a\u0000@example.com' }, cc: 'b\u0001@example.com', bcc: 'c\u0002@example.com' },
            ['To "a\\u0000@example.com"', 'CC "b\\u0001@example.com"', 'BCC "c\\u0002@example.com"'],
        ],
        [
            'nothing in clean recipients',
            { to: { email: 'a@example.com' }, cc: '"B" <b@example.com>', bcc: 'c@example.com' },
            [],
        ],
        ['nothing in empty or missing fields', { to: { email: '' }, cc: '', bcc: undefined }, []],
        [
            'nothing for tabs and line breaks',
            { to: { email: 'a@example.com' }, cc: 'b@example.com,\n\tc@example.com\r\n' },
            [],
        ],
        ['nothing for a space or a printable symbol', { cc: '"Jo ~" <jo@example.com>' }, []],
        ['nothing for unicode', { cc: '"Jö 🙂" <jö@exämple.com>' }, []],
        [
            'nothing in the To display name, which the send strips',
            { to: { email: 'jo@example.com', name: 'Jo\u0001' } as EmailRecipients['to'] },
            [],
        ],
        [
            'nothing in a value that is not a string',
            { to: { email: 42 }, cc: { a: '\u0000' } } as unknown as EmailRecipients,
            [],
        ],
    ])('finds %s', (_name, recipients, expected) => {
        expect(fieldsWithControlCharacters(recipients)).toEqual(expected)
    })

    it.each([
        ['at the start', `\u0001${'a'.repeat(200)}`, `"\\u0001${'a'.repeat(99)}..."`],
        [
            'in the middle',
            `${'a'.repeat(200)}\u0001${'b'.repeat(200)}`,
            `"...${'a'.repeat(50)}\\u0001${'b'.repeat(49)}..."`,
        ],
        ['at the end', `${'a'.repeat(200)}\u0001`, `"...${'a'.repeat(99)}\\u0001"`],
    ])('logs the 100 characters around a control character %s of a long list', (_name, cc, expected) => {
        expect(fieldsWithControlCharacters({ cc })).toEqual([`CC ${expected}`])
    })

    it.each([
        ['null characters between letters', 'a\u0000'.repeat(32000)],
        ['a malformed list with a trailing null character', 'a-'.repeat(40000) + '\u0000'],
        ['a malformed quoted name', '\u0001"' + '\\"'.repeat(20000)],
    ])('checks a long list with %s in linear time', (_name, cc) => {
        const started = performance.now()
        expect(fieldsWithControlCharacters({ cc })).toHaveLength(1)
        expect(performance.now() - started).toBeLessThan(500)
    })
})

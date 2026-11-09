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
        ['a CC address in angle brackets', { cc: '"Jo" <jo\u0001@example.com>' }, ['CC "jo\\u0001@example.com"']],
        ['a quoted CC local part', { cc: '"jo\u0001"@example.com' }, ['CC "jo\\u0001@example.com"']],
        [
            'the second entry of a comma list',
            { cc: 'ok@example.com, jo\u0002@example.com' },
            ['CC "jo\\u0002@example.com"'],
        ],
        [
            'the second entry of a semicolon list',
            { cc: 'ok@example.com; jo\u0002@example.com' },
            ['CC "jo\\u0002@example.com"'],
        ],
        ['a member of a group', { cc: 'Team: ok@example.com, jo\u0003@example.com;' }, ['CC "jo\\u0003@example.com"']],
        ['DEL in a CC address', { cc: 'jo\u007F@example.com' }, ['CC "jo\\u007f@example.com"']],
        ['a BCC address', { bcc: 'ok@example.com, jo\u0000@example.com' }, ['BCC "jo\\u0000@example.com"']],
        [
            'two CC addresses',
            { cc: 'a\u0001@example.com, b\u0002@example.com' },
            ['CC "a\\u0001@example.com"', 'CC "b\\u0002@example.com"'],
        ],
        [
            'a CC address in a list that already holds private-use characters',
            { cc: '"Jo \uE000\uE001" <jo\u0001@example.com>' },
            ['CC "jo\\u0001@example.com"'],
        ],
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
        [
            'nothing for a control picture in an address of a list with a control character in a name',
            { to: { email: 'jo\u2400@example.com' }, cc: '"Jo\u0001" <jo\u2401@example.com>' },
            [],
        ],
        [
            'nothing for a private-use character in an address of a list with a control character in a name',
            { cc: '"Jo\u0001" <jo\uE001@example.com>' },
            [],
        ],
        [
            'nothing in the To display name',
            { to: { email: 'jo@example.com', name: 'Jo\u0001' } as EmailRecipients['to'] },
            [],
        ],
        ['nothing in a quoted CC display name', { cc: '"Jo\u0001" <jo@example.com>' }, []],
        ['nothing in an unquoted CC display name', { cc: 'Jo\u0001 <jo@example.com>' }, []],
        ['nothing in a CC comment', { cc: 'jo@example.com (Jo\u0001)' }, []],
        ['nothing for DEL in a BCC display name', { bcc: '"Jo\u007F" <jo@example.com>' }, []],
        ['nothing in a group name', { cc: 'Team\u0001: jo@example.com;' }, []],
    ])('finds %s', (_name, recipients, expected) => {
        expect(fieldsWithControlCharacters(recipients)).toEqual(expected)
    })

    it.each([
        ['a quoted display name', '"Jo\u0001" <jo@example.com>, ok@example.com'],
        ['an unquoted display name', 'Jo\u0001 <jo@example.com>, ok@example.com'],
        ['a comment', 'jo@example.com (Jo\u0001), ok@example.com'],
        ['a display name, as DEL', '"Jo\u007F" <jo@example.com>, ok@example.com'],
        ['a group name', 'Team\u0001: jo@example.com, ok@example.com;'],
    ])('delivers every mailbox of a CC list whose control character sits in %s', async (_name, cc) => {
        expect(fieldsWithControlCharacters({ cc })).toEqual([])
        const delivered = await removeSuppressedRecipients({ cc }, () => Promise.resolve(false))
        expect(delivered.cc).not.toMatch(/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/)
        expect(delivered.cc).toMatch(/(^|<)jo@example\.com(>|,)/)
        expect(delivered.cc).toMatch(/ok@example\.com$/)
    })
})

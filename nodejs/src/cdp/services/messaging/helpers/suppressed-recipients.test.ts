import { EmailRecipients, SuppressedRecipientsResult, removeSuppressedRecipients } from './suppressed-recipients'

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

import { emailRecipientHash } from './email-recipient-hash'

describe('emailRecipientHash', () => {
    // Django hashes recipients for the lookup by recipient, so it must assert this same literal.
    it.each(['  Jane.Doe@Example.COM ', 'jane.doe@example.com'])('hashes %p to the shared test vector', (address) => {
        expect(emailRecipientHash(address, '00beef0000beef0000beef0000beef00')).toBe(
            'e7b76d6c58afac8ef397725c6b81a97de6e27926a51b37ee79b281032c3f2aa7'
        )
    })
})

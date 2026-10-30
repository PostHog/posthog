import { addressFromLocalPart, addressLocalPart, senderAddressError } from './emailSenderFields'

describe('emailSenderFields', () => {
    const withDomain = { id: 1, config: { email: 'hello@example.com', domain: 'example.com' } }
    // Senders without a stored domain are checked against their own address's domain.
    const withoutDomain = { id: 2, config: { email: 'hello@example.com' } }
    const otherDomain = { id: 3, config: { email: 'hello@example.org', domain: 'example.org' } }

    test.each([
        ['an empty address', '', withDomain],
        ['an address on the verified domain', 'security@example.com', withDomain],
        ['an address whose domain differs only in case', 'security@Example.COM', withDomain],
        ['a templated address', '{{ variables.alias }}@example.org', withDomain],
        ['an address on the domain every rotating sender shares', 'security@example.com', [withDomain, withoutDomain]],
    ])('accepts %s', (_name, address, sender) => {
        expect(senderAddressError(address, sender)).toBeNull()
    })

    test.each([
        ['an address on another domain', 'security@example.org', withDomain, 'Use an address on example.com'],
        ['an address off the domain of the sender address', 'security@example.org', withoutDomain, 'example.com'],
        ['a name instead of an address', 'Security team', withDomain, 'Enter one email address'],
        ['two addresses', 'a@example.com, b@example.com', withDomain, 'Enter one email address'],
        ['an address too long to deliver', `${'a'.repeat(250)}@example.com`, withDomain, 'at most 254 characters'],
        [
            'any address for rotating senders on different domains',
            'security@example.com',
            [withDomain, otherDomain],
            'different domains',
        ],
        [
            'a local part for rotating senders on different domains',
            'security',
            [withDomain, otherDomain],
            'different domains',
        ],
    ])('rejects %s', (_name, address, sender, expected) => {
        expect(senderAddressError(address, sender)).toContain(expected)
    })

    test.each([
        ['adds the domain to a local part', 'security', 'security@example.com'],
        [
            'keeps a templated local part on the domain',
            'team-{{ variables.team }}',
            'team-{{ variables.team }}@example.com',
        ],
        [
            'keeps a lone template expression as the whole address',
            '{{ event.properties.sender }}',
            '{{ event.properties.sender }}',
        ],
        ['keeps an address that already has a domain', 'security@example.org', 'security@example.org'],
        ['clears the address when the input is empty', '  ', undefined],
    ])('%s', (_name, localPart, expected) => {
        expect(addressFromLocalPart(localPart, 'example.com')).toEqual(expected)
    })

    test.each([
        ['strips the verified domain', 'security@Example.com', 'security'],
        ['shows an off-domain address whole so its error is visible', 'security@example.org', 'security@example.org'],
    ])('%s', (_name, address, expected) => {
        expect(addressLocalPart(address, 'example.com')).toEqual(expected)
    })
})

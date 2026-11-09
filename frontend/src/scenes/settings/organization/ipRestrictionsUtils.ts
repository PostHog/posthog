import ipaddr from 'ipaddr.js'

function parseAddress(value: string): ipaddr.IPv4 | ipaddr.IPv6 | null {
    if (!value || value.includes('/')) {
        return null
    }
    if (!value.includes(':') && !ipaddr.IPv4.isValidFourPartDecimal(value)) {
        return null
    }
    if (
        value.includes(':') &&
        value.includes('.') &&
        !ipaddr.IPv4.isValidFourPartDecimal(value.slice(value.lastIndexOf(':') + 1))
    ) {
        return null
    }
    try {
        return ipaddr.parse(value)
    } catch {
        return null
    }
}

export function isValidIpAddress(value: string): boolean {
    return parseAddress(value.trim()) !== null
}

function parseRestriction(value: string): [ipaddr.IPv4 | ipaddr.IPv6, number] | null {
    const [addressString, prefixString, ...extra] = value.trim().split('/')
    if (!addressString || extra.length > 0) {
        return null
    }
    const address = parseAddress(addressString)
    if (!address) {
        return null
    }
    const maxPrefix = address.kind() === 'ipv6' ? 128 : 32
    if (prefixString === undefined) {
        return [address, maxPrefix]
    }
    if (!/^\d+$/.test(prefixString)) {
        if (address.kind() !== 'ipv4' || !ipaddr.IPv4.isValidFourPartDecimal(prefixString)) {
            return null
        }
        const mask = ipaddr.IPv4.parse(prefixString)
        const prefix =
            mask.prefixLengthFromSubnetMask() ??
            new ipaddr.IPv4(mask.octets.map((octet) => octet ^ 255)).prefixLengthFromSubnetMask()
        return prefix === null ? null : [address, prefix]
    }
    const prefix = Number(prefixString)
    return prefix <= maxPrefix ? [address, prefix] : null
}

export function isValidIpOrCidr(value: string): boolean {
    return parseRestriction(value) !== null
}

export function isIpAllowed(ip: string, restrictions: string[]): boolean {
    const address = parseAddress(ip.trim())
    if (!address) {
        return false
    }
    return (
        restrictions.length === 0 ||
        restrictions.some((restriction) => {
            const parsed = parseRestriction(restriction)
            return parsed !== null && parsed[0].kind() === address.kind() && address.match(parsed[0], parsed[1])
        })
    )
}

export function getIPRestrictionsError(entries: string[]): string | null {
    if (entries.length > 100) {
        return 'You can add at most 100 IP addresses or CIDR blocks.'
    }
    if (entries.some((entry) => !isValidIpOrCidr(entry))) {
        return 'Enter a valid IP address or CIDR block, such as 203.0.113.4 or 10.0.0.0/8.'
    }
    return null
}

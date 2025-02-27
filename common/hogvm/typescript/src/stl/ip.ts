/**
 * Checks if an IP address (IPv4 or IPv6) is within a given CIDR range
 * @param address The IP address to check
 * @param prefix The CIDR notation range (e.g., "192.168.1.0/24" or "2001:db8::/32")
 * @returns boolean indicating if the address is in the specified range, false for invalid inputs
 */
export function isIPAddressInRange(address: string, prefix: string): boolean {
    // Validate inputs
    if (!address || !prefix || typeof address !== 'string' || typeof prefix !== 'string') {
        return false
    }

    // Parse the CIDR prefix
    const [networkAddress, cidrMask] = prefix.split('/')
    if (!networkAddress || !cidrMask) {
        return false
    }

    const mask = parseInt(cidrMask, 10)
    if (isNaN(mask)) {
        return false
    }

    // Determine IP version
    const isIPv4 = address.includes('.') && networkAddress.includes('.')
    const isIPv6 = address.includes(':') && networkAddress.includes(':')

    // If versions don't match or can't be determined
    if (!isIPv4 && !isIPv6) {
        return false
    }

    if (isIPv4) {
        // Handle IPv4
        if (mask < 0 || mask > 32) {
            return false
        }

        try {
            const ipNum = ipv4ToInt(address)
            const prefixNum = ipv4ToInt(networkAddress)

            // If conversion failed
            if (ipNum === -1 || prefixNum === -1) {
                return false
            }

            // Create the mask by shifting bits
            const shiftBits = 32 - mask
            const netMask = shiftBits === 32 ? 0 : ~((1 << shiftBits) - 1)

            // Check if the IP is in range by applying the mask
            return (ipNum & netMask) === (prefixNum & netMask)
        } catch {
            return false
        }
    } else {
        // Handle IPv6
        if (mask < 0 || mask > 128) {
            return false
        }

        try {
            const ipBytes = ipv6ToBytes(address)
            const networkBytes = ipv6ToBytes(networkAddress)

            // If conversion failed
            if (!ipBytes || !networkBytes) {
                return false
            }

            // Compare each byte according to the mask
            const fullBytes = Math.floor(mask / 8)
            const remainingBits = mask % 8

            // Check full bytes (all bits are compared)
            for (let i = 0; i < fullBytes; i++) {
                if (ipBytes[i] !== networkBytes[i]) {
                    return false
                }
            }

            // Check the byte with partial bits if necessary
            if (remainingBits > 0 && fullBytes < 16) {
                // Create a mask for the partial byte
                const byteMask = 0xff - ((1 << (8 - remainingBits)) - 1)
                if ((ipBytes[fullBytes] & byteMask) !== (networkBytes[fullBytes] & byteMask)) {
                    return false
                }
            }

            return true
        } catch {
            return false
        }
    }
}

/**
 * Converts an IPv4 address to its integer representation
 * @returns number representing the IP, or -1 if invalid
 */
function ipv4ToInt(ip: string): number {
    const parts = ip.split('.')
    if (parts.length !== 4) {
        return -1
    }

    // Check each part is a valid number between 0-255
    for (let i = 0; i < 4; i++) {
        const part = parseInt(parts[i], 10)
        if (isNaN(part) || part < 0 || part > 255 || parts[i] !== part.toString()) {
            return -1
        }
    }

    // Convert to integer
    return (
        ((parseInt(parts[0], 10) << 24) |
            (parseInt(parts[1], 10) << 16) |
            (parseInt(parts[2], 10) << 8) |
            parseInt(parts[3], 10)) >>>
        0
    ) // Unsigned right shift to ensure positive number
}

/**
 * Converts an IPv6 address to a byte array (16 bytes)
 * @returns Uint8Array of bytes or null if invalid
 */
function ipv6ToBytes(ip: string): Uint8Array | null {
    const bytes = new Uint8Array(16)

    // Basic validation
    if (!ip || !ip.includes(':')) {
        return null
    }

    // Handle shortened IPv6 addresses
    let segments: string[]
    if (ip.includes('::')) {
        // Cannot have multiple :: in a valid address
        if ((ip.match(/::/g) || []).length > 1) {
            return null
        }

        const parts = ip.split('::')
        const beforeEmpty = parts[0] ? parts[0].split(':') : []
        const afterEmpty = parts[1] ? parts[1].split(':') : []

        if (beforeEmpty.length + afterEmpty.length > 7) {
            return null
        }

        const missingSegments = 8 - beforeEmpty.length - afterEmpty.length

        segments = [...beforeEmpty, ...Array(missingSegments).fill('0'), ...afterEmpty]
    } else {
        segments = ip.split(':')
        if (segments.length !== 8) {
            return null
        }
    }

    // Validate and convert segments to bytes
    for (let i = 0; i < 8; i++) {
        if (!segments[i] && segments[i] !== '0') {
            return null
        }

        const value = parseInt(segments[i], 16)
        if (isNaN(value) || value < 0 || value > 0xffff) {
            return null
        }

        bytes[i * 2] = (value >> 8) & 0xff
        bytes[i * 2 + 1] = value & 0xff
    }

    return bytes
}

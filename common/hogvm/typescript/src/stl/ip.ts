import { ExecOptions } from '../types'

/**
 * Determines if an IP address is contained in a network represented in the CIDR notation.
 */
export function isIPAddressInRange(address: string, prefix: string, options?: ExecOptions): boolean {
    const ipaddr = options?.external?.ipaddr
    if (!ipaddr) {
        throw new Error('The ipaddr.js module is required for "isIPAddressInRange" to work.')
    }
    try {
        const parsedAddress = ipaddr.parse(address)
        const [network, length] = ipaddr.parseCIDR(prefix)
        return parsedAddress.match(network, length)
    } catch (e) {
        // return false for invalid IP/CIDR
        return false
    }
}

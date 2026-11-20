import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

export function copyForwardingAddress(forwardingAddress: string): void {
    void navigator.clipboard.writeText(forwardingAddress)
    lemonToast.success('Forwarding address copied')
}

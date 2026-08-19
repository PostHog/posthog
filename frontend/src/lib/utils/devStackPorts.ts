export function devProxyPortForBackendPort(port: number): number | null {
    return port >= 8000 && (port - 8000) % 100 === 0 ? port + 10 : null
}

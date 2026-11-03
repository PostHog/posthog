// The origin of a PostHog host: its scheme, host name and port, without a path or a trailing
// slash, so `https://eu.posthog.com/` and `https://eu.posthog.com` are the same login. Only
// `hostKey` makes one, so every map of logins uses the same form.
export type HostKey = string & { readonly __brand: 'HostKey' }

export function hostKey(host: string): HostKey {
    return (URL.canParse(host) ? new URL(host).origin : host) as HostKey
}

export function trimHost(host: string): string {
    return host.replace(/\/+$/, '')
}

// Keeps the path a self-hosted PostHog can sit under, such as https://example.com/posthog.
export function hostUrl(host: string, path: string): URL {
    return new URL(path, `${trimHost(host)}/`)
}

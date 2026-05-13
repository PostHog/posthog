export const deriveLivestreamHost = (appHost: string): string => {
  const normalized = appHost.replace(/\/$/, '')

  // Known cloud hosts
  switch (normalized) {
    case 'https://us.posthog.com':
    case 'https://app.posthog.com':
      return 'https://live.us.posthog.com'
    case 'https://eu.posthog.com':
      return 'https://live.eu.posthog.com'
    case 'https://app.dev.posthog.dev':
      return 'https://live.dev.posthog.dev'
  }

  // For self-hosted or unknown hosts, try to derive livestream host
  // by replacing the subdomain with 'live'
  try {
    const url = new URL(normalized)

    // Local development
    if (url.hostname === 'localhost' || url.hostname === '127.0.0.1') {
      return 'http://localhost:8010'
    }

    // Self-hosted: attempt to derive by replacing first subdomain with 'live'
    // e.g., posthog.example.com -> live.example.com
    // e.g., app.posthog.example.com -> live.posthog.example.com
    const parts = url.hostname.split('.')
    if (parts.length >= 2) {
      parts[0] = 'live'
      return `${url.protocol}//live.${parts.slice(1).join('.')}`
    }

    // Fallback for single-part hostnames
    return `${url.protocol}//live.${url.hostname}`
  } catch {
    // If URL parsing fails, fall back to localhost for development
    return 'http://localhost:8010'
  }
}

export const deriveLivestreamHost = (appHost: string): string => {
  const normalized = appHost.replace(/\/$/, '')

  switch (normalized) {
    case 'https://us.posthog.com':
    case 'https://app.posthog.com':
      return 'https://live.us.posthog.com'
    case 'https://eu.posthog.com':
      return 'https://live.eu.posthog.com'
    case 'https://app.dev.posthog.dev':
      return 'https://live.dev.posthog.dev'
    default:
      return 'http://localhost:8010'
  }
}

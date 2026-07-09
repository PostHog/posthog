import { needsClientSsl } from './create-pool'

describe('needsClientSsl', () => {
    it.each([
        // Loopback / local dev — no SSL.
        ['postgres://u:p@localhost:5432/db', false],
        ['postgres://u:p@127.0.0.1:5432/db', false],
        // In-cluster pgbouncer reached by a bare k8s service name (no dot) —
        // the bouncer speaks plaintext to clients, so requesting SSL here is the
        // bug that yields "The server does not support SSL connections".
        ['postgres://u:p@pgbouncer-agent-platform-write:6543/db', false],
        ['postgres://u:p@posthog-web-django-pgbouncer-agent-platform:6543/db', false],
        // In-cluster FQDN — also plaintext to clients.
        ['postgres://u:p@pgbouncer-agent-platform-write.posthog.svc.cluster.local:6543/db', false],
        // Direct external Aurora (dotted RDS host) — needs client SSL.
        ['postgres://u:p@agent-platform-dev.cluster-abc.us-east-1.rds.amazonaws.com:5432/db', true],
    ])('%s -> needsClientSsl=%s', (connectionString, expected) => {
        expect(needsClientSsl(connectionString as string)).toBe(expected)
    })
})

/**
 * Standalone runnable `dogs` OAuth IdP + demo API for the local identity-linking
 * demo. Same fixture the e2e harness uses, on a fixed port so an agent's
 * spec.identity_providers can point at it.
 *
 *   npx tsx scripts/dog-oauth-server.ts        # listens on :4545
 *   DOG_PORT=4600 npx tsx scripts/dog-oauth-server.ts
 *
 * Dev-only: not wired into any production service.
 */

import { startDogServer } from '../src/harness/dog-oauth-server'

const port = Number(process.env.DOG_PORT ?? 4545)

const server = await startDogServer({ port, clientId: 'dogs-client' })

// eslint-disable-next-line no-console
console.log(
    [
        `🐶 dog OAuth IdP + demo API listening`,
        `   base      ${server.baseUrl}`,
        `   authorize ${server.authorizeUrl}`,
        `   token     ${server.tokenUrl}`,
        `   api       ${server.apiUrl}`,
        `   userinfo  ${server.userinfoUrl}`,
        ``,
        `Add to an agent spec.identity_providers:`,
        JSON.stringify(
            {
                kind: 'oauth2',
                id: 'dogs',
                authorize_url: server.authorizeUrl,
                token_url: server.tokenUrl,
                client_id: 'dogs-client',
                scopes: ['read:dog'],
                userinfo_url: server.userinfoUrl,
            },
            null,
            2
        ),
    ].join('\n')
)

process.on('SIGINT', () => server.close().then(() => process.exit(0)))
process.on('SIGTERM', () => server.close().then(() => process.exit(0)))

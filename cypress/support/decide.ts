import { decideResponse } from '../fixtures/api/decide'

export const setupFeatureFlags = (overrides: Record<string, any> = {}): void => {
    // Tricky - the new RemoteConfig endpoint is optimised to not load decide if there are no feature flags in the DB.
    // We need to intercept both the RemoteConfig and the decide endpoint to ensure that the feature flags are always loaded.

    cy.intercept('**/array/*/config', (req) =>
        req.reply(
            decideResponse({
                ...overrides,
            })
        )
    )

    cy.intercept('**/array/*/config.js', (req) =>
        req.continue((res) => {
            res.send(res.body)
        })
    )

    cy.intercept('**/flags/*', (req) =>
        req.reply(
            decideResponse({
                ...overrides,
            })
        )
    )
}

## Testing Feature Flags

The Cypress tests run with a PostHog instance that has no feature flags set up.

To test feature flags you can intercept the call to the `decide` endpoint

```javascript
// sometimes the system under test calls `/decide`
// and sometimes it calls https://app.posthog.com/decide
cy.intercept('https://app.posthog.com/decide/*', (req) =>
    req.reply(
        decideResponse({
            // add feature flags here, for e.g.
            // 'feature-flag-key': true,
        })
    )
)
```

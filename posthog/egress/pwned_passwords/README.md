# Pwned Passwords egress

Calls to the Have I Been Pwned Pwned Passwords range API, which checks a password against known data breaches.
Each call sends only the first 5 characters of the password's SHA-1 hash (k-anonymity).

## Identity

The constant scope `public`.
The API takes no credential, so there is no account to budget.

## Budget

None: calls are recorded, never gated (`RecordedEgressClient`).
Have I Been Pwned documents no rate limit for the Pwned Passwords API.
Add a gate only if it publishes one.

## Lanes and callers

No lanes, because nothing is gated.
`BreachedPasswordValidator` in `posthog/auth.py` is the caller, with the source `password_validation`.
It runs from `AUTH_PASSWORD_VALIDATORS` on signup, invite signup, password change, and password reset.
The validator accepts the password when a call fails, so a failed call never blocks a user.

## Rate-limit headers

None documented, so the domain declares no gauges.
The counter is `pwned_passwords_api_requests_total`, labeled `scope, method, endpoint, status_code, source`.
The endpoint label is always `range/{prefix}`, because a real hash prefix would add a label value for each password.
A failed request records the `status_code` label `exception`.

## Auth

None. The API is free to use without an API key.

## Sources

- [Have I Been Pwned API v3, Pwned Passwords](https://haveibeenpwned.com/API/v3#PwnedPasswords): "The Pwned Passwords API is freely accessible without the need for a subscription and API key."
- [Searching by range](https://haveibeenpwned.com/API/v3#SearchingPwnedPasswordsByRange): the endpoint is `GET https://api.pwnedpasswords.com/range/{first 5 hash chars}`, and the response is one `SUFFIX:COUNT` line per hash suffix.
- [Padding](https://haveibeenpwned.com/API/v3#PwnedPasswordsPadding): the `Add-Padding: true` header "pads out responses to ensure all results contain a random number of records between 800 and 1,000."
- [Rate limiting](https://haveibeenpwned.com/API/v3#RateLimiting): "There is no rate limit on the Pwned Passwords API." The only rate-limit header documented is `retry-after`, for the breach, paste, and stealer log APIs.

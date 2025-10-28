# Session `019951bb-a319-7557-8d3f-4928ddd0b991`
Failure. Blocking server errors prevented login; password-reset attempt did not recover, leading to abandonment.

## Segment #0
Repeated failed login attempts. User spent 13s, performing 46 events.

### What the user did 
- Entered email to begin login at 00:00:03, as "$autocapture" (click) event (event_uuid: `019951bb-b150-70f2-a6e5-002a76e98077`).
- Issues noticed: confusion, blocking exception. Multiple login submissions returned server errors at 00:00:03, as "client_request_failure" event (event_uuid: `019951bb-b439-7b26-8c47-485cbc644765`).

### Segment outcome
Failure. User repeatedly submitted login form but every attempt hit blocking API errors.

## Segment #1
Password-reset detour then exit. User spent 4s, performing 8 events.

### What the user did 
- Clicked "Forgot your password?" link at 00:00:15, as "$autocapture" (click) event (event_uuid: `019951bb-e0af-7c39-a7d7-83c9ee4adabf`).
- Used copy-to-clipboard on reset page at 00:00:16, as "$autocapture" (click) event (event_uuid: `019951bb-e449-7c22-bf72-9e6ec5753f0c`).
- Issues noticed: abandonment. Left without regaining account access at 00:00:18, as "$pageleave" event (event_uuid: `019951bb-eced-732e-9998-0d91cbbcb6eb`).

### Segment outcome
Failure. Tried password reset, copied link, returned to login, then abandoned session.
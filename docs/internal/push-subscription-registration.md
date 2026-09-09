# Push subscription registration

How a mobile device registers a push token, and what an SDK has to do so that a project without push
configured does not generate a request per device per app open.

## The flow

A mobile SDK with push capture enabled posts its device token to `/api/push_subscriptions/` when the
app starts. The server resolves the `app_id` to a Firebase or APNs integration on the team and stores
the token as a `$device_push_subscription_<app_id>` person property.

Push is opt-in per project, and the SDK cannot see whether a project opted in. So an app that ships
with push capture on registers against every project it reports to, configured or not.

## What the server does with an unconfigured `app_id`

`POST` answers `200` with `{"stored": false, "push_enabled": false}` and does not store the token.
`DELETE` still runs its `$unset`, because a logout has to clear a subscription stored while an
integration existed.

The 200 is deliberate. A 4xx makes this the error path for the majority of the requests the endpoint
receives, which is both wrong (nothing about the request was invalid) and expensive to everything
that watches non-2xx rates.

## The `push.appIds` remote config key

Remote config carries the list of `app_id`s a team can accept registrations for:

```json
{ "push": { "appIds": ["my-firebase-project", "com.example.app"] } }
```

Firebase contributes its `project_id`, APNs its `bundle_id`. The key is always present, including as
an empty list.

**Absent and empty are not the same thing.** Absent means the server predates this key, so the SDK
cannot conclude anything and must attempt the registration. Empty means the server said this team has
no push configured. An SDK that treats absent as empty stops registering against every older
self-hosted deployment.

## What an SDK has to do

1. **Absent key** — register as before.
2. **`app_id` not in `appIds`** — skip the request entirely. There is nothing to register against, and
   the server would discard it.
3. **`app_id` appears in `appIds` having been absent before** — clear any local record that the token
   was already delivered, and register.

Rule 3 is the one that is easy to miss, and without it a project that turns push on never reaches the
devices it already has.

## The list has to be cached on disk

Registration runs at startup. Remote config resolves asynchronously, so on a cold start the SDK
usually reaches the point of registering before `/config` has answered. An SDK that only consults the
freshly fetched list therefore still sends the request it was supposed to skip, and the gate takes
effect from the second launch onward rather than the first.

So the push slice has to be persisted when it arrives and preloaded on the next start, before the
first registration attempt. On Android that is the pattern `errorTracking` already uses:
`processErrorTrackingConfig` writes to `config.cachePreferences`, and `preloadErrorTrackingConfig`
restores it on launch. iOS mirrors it.

This interacts with rule 1. A cold start with nothing cached is not the same as an absent key: the SDK
has never heard from this server, so it registers, exactly as rule 1 says. Only a cached empty list
means "skip".

## Why rule 3 exists

Both mobile SDKs persist a delivered marker (`deliveredForDistinctId`) alongside the pending
registration, and skip the request when the stored token, `app_id` and distinct id all match. The
marker is written on any 2xx and survives a process restart, which is what stops a device re-posting
on every launch.

It also means a device that registered while its project was unconfigured recorded a success for a
token the server never kept. Nothing on the server can undo that: no response reaches a device that
has stopped asking. The only triggers left are a token rotation, an `identify()` to a different
distinct id, or a reinstall.

So a device that registered before its project was configured stays unreachable until it updates to an
SDK that implements rule 3.

## Server-side notes

- `build_push_config` in `products/messaging/backend/remote_config.py` derives the list. A `post_save`
  and `post_delete` receiver on `Integration` rebuilds the team's remote config when a `firebase` or
  `apns` integration changes, so a project that configures push is published without waiting for an
  unrelated write.
- Non-string identifiers are skipped. `Integration.config` is a `JSONField`, and an unusable value
  would otherwise raise inside `build_config` and leave the team's whole remote config stale.
- Registration outcomes are observable through `push_subscription_rejection{code, method}`,
  `push_subscription_discarded{reason}`, and the `push_subscription_discarded` log line, which is
  emitted once per team per minute rather than once per request.

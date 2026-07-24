# PostHog Mobile App

React Native mobile app built with Expo and expo-router.

## Quick Start

From the **repository root**:

```bash
# Install dependencies (workspaces are wired up, so the root install covers mobile)
pnpm install

# Build and run on iOS simulator
pnpm --filter @posthog/mobile ios

# Start the development server (after initial build)
pnpm --filter @posthog/mobile start
```

> First-time iOS setup also requires the **watchOS SDK** to be installed in Xcode — see [Prerequisites](#prerequisites).

## Tech Stack

- [Expo](https://expo.dev) - Build tooling, native APIs, OTA updates
- [expo-router](https://docs.expo.dev/router/introduction/) - File-based routing
- [NativeWind](https://www.nativewind.dev/) - Tailwind CSS for React Native
- [React Query](https://tanstack.com/query) - Async data fetching and caching
- [Zustand](https://zustand-demo.pmnd.rs/) - Client state management (UI state, selections, local flags)
- [Phosphor Icons](https://phosphoricons.com/) - Icon library

## Architecture

### Feature Folders

Code is organized by feature in `src/features/`. Each feature is self-contained with its own components, hooks, stores, and API logic.

```
src/features/
├── auth/           # Authentication & user session
│   ├── hooks/
│   ├── lib/
│   ├── stores/
│   └── types.ts
├── chat/           # PostHog AI chat interface
│   ├── components/
│   ├── hooks/
│   ├── stores/
│   └── types.ts
├── conversations/  # PostHog AI conversation list & management
│   ├── api.ts
│   ├── components/
│   ├── hooks/
│   └── stores/
└── tasks/          # Task management
    ├── api.ts
    ├── components/
    ├── hooks/
    └── stores/
```

### File-Based Routing

Routes for the screens are defined by the file structure in `src/app/` using expo-router. 

- `(tabs)/` - Parentheses create a layout group (tab navigator)
- `_layout.tsx` - Configures the navigator for that directory
- `[id].tsx` - Square brackets define dynamic route parameters
- Stacks and modals live outside tab group, configured in `_layout.tsx`

```
src/app/
├── _layout.tsx        # Root layout
├── index.tsx          # Entry redirect
├── auth.tsx           # Auth screen (unauthenticated)
├── (tabs)/            # Tabs group
│   ├── _layout.tsx    # Layout for all tabs
│   ├── index.tsx      # Home tab (Conversations)
│   ├── tasks.tsx      # Tasks tab
│   └── settings.tsx   # Settings tab
├── chat/              # Chat stack
│   ├── index.tsx      # New chat
│   └── [id].tsx       # Chat by ID (dynamic route)
└── task/              # Task stack
    ├── index.tsx      # New task
    └── [id].tsx       # Task by ID (dynamic route)
```

### Shared Code

```
src/
├── components/     # Reusable UI components (Text, etc.)
└── lib/
    ├── posthog.ts  # Analytics setup
    ├── queryClient.ts  # React Query client
    ├── theme.ts    # Design tokens
    └── logger.ts   # Logger setup
```

## Prerequisites

- Node.js 22+
- pnpm 10.23.0
- Xcode (for iOS development)
- **watchOS SDK** (iOS builds embed the Apple Watch companion; without this SDK installed, `expo run:ios` fails with `watchOS X.X must be installed in order to run the scheme`)
  - Install via `xcodebuild -downloadPlatform watchOS`, or in Xcode → **Settings → Components → Platforms** → download the latest watchOS
- Android Studio (for Android development)
- EAS CLI is optional — all `eas` commands below are invoked via `npx eas`. Install globally with `npm install -g eas-cli` only if you prefer the bare command.

## Commands

### From Repository Root

All commands use `pnpm --filter @posthog/mobile <script>` to target this workspace package. (`-F` is a shorter alias for `--filter`.)

**Development server:**
```bash
pnpm --filter @posthog/mobile start          # Start Expo dev server
pnpm --filter @posthog/mobile start:clear    # Start with cleared Metro cache
```

**Build and run:**
```bash
pnpm --filter @posthog/mobile ios            # iOS simulator
pnpm --filter @posthog/mobile ios:device     # iOS device (requires Apple Developer account)
pnpm --filter @posthog/mobile android        # Android emulator/device
```

**Native code generation:**
```bash
pnpm --filter @posthog/mobile prebuild         # Generate ios/ and android/ folders
pnpm --filter @posthog/mobile prebuild:clean   # Delete and regenerate (when adding native deps)
```

**EAS builds:**
```bash
pnpm --filter @posthog/mobile build:dev          # Development build (iOS, cloud)
pnpm --filter @posthog/mobile build:dev:local    # Development build (iOS, local)
pnpm --filter @posthog/mobile build:preview      # Preview build (iOS)
pnpm --filter @posthog/mobile build:production   # Production build (iOS)
```

**TestFlight:**
```bash
pnpm --filter @posthog/mobile testflight     # Submit to TestFlight
```

**Utilities:**
```bash
pnpm install                                  # Installs all workspaces, including mobile
pnpm --filter @posthog/mobile lint            # Run Biome check
pnpm --filter @posthog/mobile lint:fix        # Run Biome check with auto-fix
pnpm --filter @posthog/mobile format          # Run Biome format
```

### From apps/mobile/ Directory

```bash
cd apps/mobile

# Development server
pnpm start                  # alias for: expo start
pnpm start:clear            # alias for: expo start --clear

# Build and run
pnpm ios                    # alias for: expo run:ios
pnpm ios:device             # alias for: expo run:ios --device
pnpm android                # alias for: expo run:android

# Generate native code
pnpm prebuild               # alias for: expo prebuild
pnpm prebuild:clean         # alias for: expo prebuild --clean

# EAS builds (iOS) — pnpm aliases exist for these
pnpm build:dev              # eas build --profile development --platform ios
pnpm build:dev:local        # eas build --profile development --platform ios --local
pnpm build:preview          # eas build --profile preview --platform ios
pnpm build:production       # eas build --profile production --platform ios

# EAS builds (Android) — no aliases, invoke directly
npx eas build --profile development --platform android
npx eas build --profile preview --platform android
npx eas build --profile production --platform android

# TestFlight
pnpm testflight             # alias for: eas submit --platform ios

# Linting
pnpm lint
pnpm lint:fix
pnpm format
```

## Prebuild Explained

`expo prebuild` generates the native `ios/` and `android/` folders from your Expo configuration.

**When to run `prebuild`:**
- First time setting up the project
- After adding/removing native dependencies (e.g., `expo-camera`, `react-native-maps`)
- After changing `app.json` iOS/Android configuration
- After updating Expo SDK version

**When to use `--clean`:**
- Switching between Expo SDK versions
- Native build is failing and you want a fresh start
- You've made manual changes to native files that you want to discard

The `--clean` flag removes existing `ios/` and `android/` directories before regenerating.

## Apple Watch companion

> The iOS app embeds the watchOS companion as part of its build, so **the watchOS SDK must be installed in Xcode** even if you're only running on an iPhone simulator. Without it, `expo run:ios` fails before compilation with `watchOS X.X must be installed in order to run the scheme`. Install via `xcodebuild -downloadPlatform watchOS` or Xcode → **Settings → Components → Platforms**. This is a one-time setup.

The watchOS companion is a native SwiftUI target generated during Expo prebuild by the local config plugin at `plugins/withWatchApp.js`.

Canonical native source lives outside generated iOS output:

- `native/watch/` — SwiftUI watch app source, Info.plists, and entitlements
- `native/ios/` — iPhone WatchConnectivity bridge

Generated output lives under `ios/`, including `ios/watch/`, `ios/PostHog/WatchTaskControlModule.*`, and `PostHog.xcodeproj/project.pbxproj`.

### Watch architecture

- iPhone remains the authenticated relay for the paired watch.
- Mobile derives compact task snapshots from task/session state and sends them through WatchConnectivity.
- Desktop-started local tasks work through the shared PostHog task run log/status backend, then iPhone relays to the watch.
- Watch actions send compact commands back to iPhone, which routes them through existing mobile commands (`permission_response`, `cancel`, retry/resume, and handoff URLs).
- Direct watch-to-Mac WatchConnectivity is not supported by Apple; Mac handoff uses `posthog-code://task/{taskId}/run/{taskRunId}`.

### Rebuilding native watch targets

```bash
cd apps/mobile
pnpm prebuild
# or, when regenerating native projects:
pnpm prebuild:clean
```

The `./plugins/withWatchApp` plugin copies native sources from `native/`, recreates the watch app/extension targets, and embeds them in the iOS app. If generated iOS files or Xcode targets drift, update `native/` and rerun prebuild instead of editing generated project files manually.

### Running in simulators

1. Open `ios/PostHog.xcworkspace` in Xcode.
2. Select the iOS app scheme with a paired iPhone + Apple Watch simulator destination.
3. Build/run the iOS app; Xcode should install the embedded watch app.
4. Sign in on iPhone and open or start a PostHog task.
5. Open the watch app and verify the mission overview, checklist, timeline, approvals, and blocker cards.

### Verification checklist

- Cloud task from phone/mac updates progress on watch.
- Desktop/local task shows a `Local` badge and receives progress through persisted task run logs.
- Approval card actions reach the existing permission response path.
- Stop maps to the existing cancel command; retry maps to resume/retry from iPhone.
- Open on iPhone uses `posthog://task/{taskId}`; Open on Mac uses `posthog-code://task/{taskId}/run/{taskRunId}`.
- Haptics fire once for approval needed, completion, failure/stale blockers, and action acceptance — not on every polling update.
- Intermittent connectivity shows cached mission state rather than raw errors/logs.

## Build Profiles

Defined in `eas.json`:

| Profile | Purpose | Distribution |
|---------|---------|--------------|
| `development` | Dev client with debugging | Internal only |
| `preview` | Production-like for testing | Internal only |
| `production` | App Store / Play Store release | Public |

**Local vs Cloud builds:**
- Cloud (default): Runs on Expo's servers, no local Xcode needed
- Local (`--local`): Runs on your machine, faster iteration, requires Xcode/Android SDK
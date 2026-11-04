# Real build output from getsentry/symbolic

These files come unchanged from the test fixtures of [getsentry/symbolic](https://github.com/getsentry/symbolic/tree/729b97e4391ffd0566bf616f2ec106cfc84bcdae/symbolic-testutils/fixtures), at commit `729b97e`, under the MIT license in `LICENSE`.
They hold hog to posthog-cli on output from real toolchains, next to the small fixtures built in `native/` and written in `hermes-fixtures.ts`.

| File | Origin |
| --- | --- |
| `apple/Example.framework.dSYM` | An Xcode archive build of a macOS framework, fat with x86_64 and arm64 |
| `apple/overlapping_funcs.dSYM` | An x86_64 dSYM whose functions overlap |
| `apple/symbolic-1040.dSYM` | An arm64 dSYM of a Rust binary |
| `react-native/index.android.bundle` | A Metro bundle, renamed from `react-native-metro.js` so it is detected as a React Native bundle |
| `react-native/react-native-metro.js.map` | Metro's packager map for the bundle |
| `react-native/react-native-hermes.map` | The map the Hermes compiler wrote for the bundle |

The Hermes map has no `x_hermes_function_offsets` key, which both CLIs require before they upload a Hermes map, so it covers `inject` and `clone` only.

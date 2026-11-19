# hog

## 0.1.0 — 2026-11-19

### Minor changes

- [3053ef84faf](https://github.com/PostHog/posthog/commit/3053ef84faf8dc0b144b0c001707045444d2a60b) Add `hog upgrade`, which updates hog for the way it was installed. hog says when it is a minor version or a month behind, and `hog setup` asks for the latest version. — Thanks @rafaeelaudibert!
- [946c71b8c91](https://github.com/PostHog/posthog/commit/946c71b8c913c04c7be3cf28350f38a975ceb825) `hog error-tracking upload -` and `process -` read the paths from stdin, one per line. — Thanks @rafaeelaudibert!
- [9d926f655ea](https://github.com/PostHog/posthog/commit/9d926f655eaf1489649c9d83915e644cdb2f54df) Ship hog as a binary for macOS, Linux and Windows, with install scripts, the `hog` npm package and a Homebrew formula. — Thanks @rafaeelaudibert!
- [e28b32e35f9](https://github.com/PostHog/posthog/commit/e28b32e35f9aae5f9ac6592017b85090a52149a1) Remove the commands that printed a posthog-cli command instead of running: `logs`, `tasks`, `query editor` and `api agents-md`. — Thanks @rafaeelaudibert!

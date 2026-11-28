---
cargo/posthog-cli: patch
---

The npm installer extracts the Windows binary with `tar.exe` instead of PowerShell `Expand-Archive`, which fails on some Windows images with "Cannot find an overload for ExtractToDirectory".

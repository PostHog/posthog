# Full Jest timing fixture

This is the passing Node.js JUnit output from [run 32867432062](https://github.com/PostHog/posthog/actions/runs/32867432062).

It contains the three sharded Jest files and the PostgreSQL-parity file. Use it to iterate on the real report shape:

```sh
bin/report-jest-timings --artifacts .github/scripts/fixtures/jest-timings-real-run --markdown-overview
bin/report-jest-timings --artifacts .github/scripts/fixtures/jest-timings-real-run --markdown-page 1
```

The regression test verifies all 11,446 test rows render into twelve pages, each below GitHub's 1 MiB step-summary limit.

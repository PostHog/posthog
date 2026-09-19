# Depot fork environment probe

This temporary workflow checks whether a fork pull request receives cache-related environment variables on a Depot-hosted GitHub Actions runner.
It runs the same presence check on a GitHub-hosted runner as a control.
It does not use Depot CI.

Open a draft pull request against `PostHog/posthog` that changes `.github/workflows/depot-fork-env-probe.yml`.
GitHub may require approval before it runs a fork workflow.
Read the **Depot fork environment probe** job summaries for both runners.
The summary reports the selected runner, whether the pull request comes from a fork, and whether each allowlisted variable is nonempty.
An empty variable and an unset variable both report `false`.

The workflow does not check out repository code, request GitHub token permissions, reference repository secrets, or call cache APIs.
It never prints variable values, lengths, hashes, or token claims.
The results establish variable presence for those jobs only.
They do not establish token validity, cache permissions, log masking, or behavior under different Depot settings.

A same-repository pull request with the same workflow can provide a separate comparison of fork and same-repository behavior.
The GitHub-hosted control is not a substitute for that comparison.
Close the probe pull request after collecting the results; this workflow does not need to merge.

# The Depot egress allow list

Depot runners resolve and connect only to hosts on the organization's network profile, an allow list that the devex team keeps in Depot's settings.
A host missing from the list fails like an outage: the lookup returns nothing, and the step times out or exits with a DNS error.
The list lives outside this repository, so an agent can neither read nor change it from a checkout.
What an agent can do is notice when its change needs a host, and tell the developer and devex before the change lands.

## When a change needs a new host

Any of these on a Depot runner (`depot-*` labels, and every Depot CI workflow under `.depot/`):

- A `curl`, `wget`, `go install`, `pip install --index-url`, or `npm` call to a host CI has not used before.
- A new action, container image, or compose service, which downloads its binary or image from somewhere, or pulls through a new registry.
- A webhook or API call from a step, such as a Slack, Discord, or PagerDuty post.
- A tool that phones home: version checks, crash reports, usage telemetry.
- A redirect. The host a step names can send the client somewhere else: `registry.k8s.io` redirects image pulls to `us-east4-docker.pkg.dev`, and a service behind a login answers with its identity provider's host. Each hop needs its own rule.

A test never belongs on this list.
A test that reaches a real host is a bug in the test: fake the boundary as [writing-tests](../../writing-tests/SKILL.md) says, rather than asking for a rule.

## Before you ask for a rule

- **Avoid the host.** Download from a host CI already uses, such as GitHub releases or an existing registry mirror, or cache the file.
- **Turn telemetry off at the source** with the tool's opt-out variable, rather than allowing its endpoint. Some telemetry stays on by agreement with the vendor; when a tool's telemetry already reaches its endpoint today, leave it alone.
- **Prefer an exact host to a wildcard.** `*.example.com` also matches the bare `example.com`. Depot rejects wildcards anywhere but the start, such as `api.*.example.com`.

## When the host is needed

1. **Tell the developer** in your report: the host, the workflow and job that need it, and what fails without it.
2. **Add an egress line to the PR description**, under Changes:
   `Egress: needs <host> for <workflow / job> (<why>). Not yet on the Depot allow list.`
3. **Send it to devex:**

   ```sh
   hogli devex:feedback -c question "Egress allow list: <workflow / job> needs <host> (<why>). PR #<number>."
   ```

   The command does nothing in a cloud task or agent sandbox; the PR line is the record there.

4. **Do not change the Depot network profile** yourself, even when a Depot tool would let you. Devex decides what goes on the list.

When you cannot tell whether a host is already allowed, say so; it costs devex one look.
With the Depot MCP server connected, `get_network_profile` shows the current rules.

## Finding what a job contacts

The Depot MCP server reports every lookup and connection a job made, so you can check a change instead of guessing:

- `list_github_actions_job_network_destinations` for a GitHub Actions job on a Depot runner.
- `list_ci_job_attempt_network_destinations` for a Depot CI job attempt.
- `list_organization_network_destinations` for the whole organization over a date range, and `list_network_destination_sources` to see which machine reached one host.

A source in that log is a machine ID, not a job.
To find the job, match the lookup time against jobs that ran then, and confirm in the job's own network log.

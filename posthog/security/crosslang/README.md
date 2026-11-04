# Out-of-band interaction domains

`oob_domains.json` lists the services that exist to capture out-of-band interactions, and the
DNS rebinding services. PostHog's host guards log a lookup of any of these names.

## What belongs on the list

A domain belongs here when its service exists to capture out-of-band interactions or to perform
DNS rebinding, and it has no legitimate production use.

These do not belong here:

- Wildcard-IP DNS, such as `nip.io` and `sslip.io`. Knative and OpenShift use them for real
  routes, and the IP checks already refuse the private targets.
- Request-inspection services, such as `webhook.site` and `ngrok`. Customers use them to test
  destinations.

## How to edit the list

1. Edit this file first.
2. Update each mirror. The Rust mirror is `OOB_DOMAINS` in `rust/common/dns/src/oob_domains.rs`.
   A parity test in that language fails until you do.
3. The matcher compares the canonical host, exactly or on a label boundary. Write the registrable
   domain only, lowercase, with no leading dot.

Python reads this file at runtime. Node and Rust hold mirrors, because the Rust image build
context is `rust/` and the Node build compiles from `nodejs/`.

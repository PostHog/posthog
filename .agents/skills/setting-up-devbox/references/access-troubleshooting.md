# Devbox access troubleshooting

Every `hogli devbox:*` command checks that the Coder control plane is reachable before it does anything.
Two conditions must hold.
Both fail the same way at that check, and re-running `devbox:setup` fixes neither.

## 1. The `posthog.com` tailnet

PostHog runs several tailnets.
`dev`, `prod-us`, `prod-eu`, and `internal` serve CI runners and subnet routers, and none of them route to devboxes.
People need `posthog.com`.

```bash
tailscale switch --list                 # marks the active tailnet
tailscale switch posthog.com            # if already signed into it
tailscale logout && tailscale login     # otherwise, then pick posthog.com
# macOS, when tailscale isn't on PATH:
/Applications/Tailscale.app/Contents/MacOS/Tailscale switch --list
```

The tailnet picker appears only at first sign-in, so a wrong choice persists without any warning.
In the GUI, use **Add account**, sign in, and select `posthog.com`.
Suspect this first on a new laptop, or when the user says it worked on another machine.

## 2. The ACL grant

`tailnet-policy.hujson` in `PostHog/posthog-cloud-infra` grants `group:employees` the Coder control plane at `10.70.0.1:443`.
Every employee has access, so there is no group to join and no PR to open.
If the tailnet is right and doctor still reports the control plane unreachable without a DNS cause, ask Team DevEx.

## DNS failures

Doctor can show `[ok] Tailscale connected` and still fail reachability with a DNS cause (`DNS lookup for coder.dev.posthog.dev failed`).
That means the name never reaches the internal resolver.
Check in this order:

1. **Wrong tailnet.** The other tailnets have no route to the internal zone and fail exactly like this.
2. **MagicDNS off.** "Use Tailscale DNS" in the client's DNS settings points the machine at the internal resolver. Without it, no internal name resolves.
3. **Stale upstream resolver.** MagicDNS is on and `tailscale ping <internal-ip>` answers, but names still fail. The router or ISP resolver is the problem. Adding `8.8.8.8` or `1.1.1.1` to the host's DNS settings has fixed this.

If `dig coder.dev.posthog.dev @10.90.0.2` answers while the system resolver fails, the name exists and only the resolution path is broken.

## Don't

- Don't suggest an exit node. Devboxes are tailnet peers, so an exit node isn't needed. It routes all of the user's traffic through infra, which is slower, and it hides the real cause.
- Don't suggest `/etc/hosts` or `/etc/resolver` entries. They pin internal load balancer IPs that rotate.

Team Cloud Foundations keeps the full write-up at [wiki.posthog.com/access/vpn](https://wiki.posthog.com/access/vpn#which-tailnet).

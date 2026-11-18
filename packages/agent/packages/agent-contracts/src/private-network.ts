/**
 * Whether a parsed IPv4 address falls in a non-public range: loopback
 * (127/8), "this network" (0/8), RFC1918 private space (10/8, 172.16/12,
 * 192.168/16), link-local (169.254/16, including the cloud metadata
 * endpoint), carrier-grade NAT (100.64/10, which also covers Tailscale IPs),
 * or the benchmarking range (198.18/15). Shared by every private/public host
 * classifier in this monorepo so the range table can't drift between them —
 * see `@posthog/core`'s `isPrivateHostname` and the web-fetch tool's
 * `isBlockedHost`.
 */
export function isPrivateIpv4Octets(a: number, b: number): boolean {
  if (a === 0 || a === 10 || a === 127) return true;
  if (a === 100 && b >= 64 && b <= 127) return true;
  if (a === 169 && b === 254) return true;
  if (a === 172 && b >= 16 && b <= 31) return true;
  if (a === 192 && b === 168) return true;
  return a === 198 && (b === 18 || b === 19);
}

/**
 * The IPv4 address embedded in an IPv4-mapped IPv6 literal (`::ffff:…`), or
 * undefined for any other host. `URL#hostname` normalizes the embedded address
 * into hex groups (`::ffff:127.0.0.1` becomes `::ffff:7f00:1`), so both the
 * hex-group form and the raw dotted form are decoded.
 */
function ipv4MappedOctets(
  host: string,
): [number, number, number, number] | undefined {
  const hex = host.match(/^::ffff:([0-9a-f]{1,4}):([0-9a-f]{1,4})$/);
  if (hex) {
    const hi = Number.parseInt(hex[1], 16);
    const lo = Number.parseInt(hex[2], 16);
    return [(hi >> 8) & 0xff, hi & 0xff, (lo >> 8) & 0xff, lo & 0xff];
  }
  const dotted = host.match(
    /^::ffff:(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/,
  );
  if (dotted) {
    const octets = dotted.slice(1).map(Number);
    if (octets.some((octet) => octet > 255)) return undefined;
    return octets as [number, number, number, number];
  }
  return undefined;
}

/**
 * Whether a bracket-free, lowercased IPv6 literal is non-public: loopback
 * (`::1`), unspecified (`::`/`::0`), link-local (fe80::/10), unique-local
 * (fc00::/7), or an IPv4-mapped address whose embedded IPv4 is private. Shared
 * by `@posthog/core`'s `isPrivateHostname` and the web-fetch tool's
 * `isBlockedHost` so the IPv6-literal kernel can't drift between them; each
 * still layers its own non-literal rules (bare intranet names, `.local`
 * suffixes) on top.
 */
export function isPrivateIpv6Literal(host: string): boolean {
  if (host === "::1") return true;
  if (host === "::" || host === "::0") return true;
  if (/^fe[89ab]/.test(host)) return true; // link-local fe80::/10
  if (/^f[cd]/.test(host)) return true; // unique-local fc00::/7
  const octets = ipv4MappedOctets(host);
  return octets ? isPrivateIpv4Octets(octets[0], octets[1]) : false;
}

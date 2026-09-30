import { describe, expect, it } from "vitest";
import {
  isPrivateHostname,
  isPrivateIpv4Octets,
  isPrivateIpv6Literal,
} from "./private-network";

describe("isPrivateIpv4Octets", () => {
  it.each([
    [0, 1, "this network"],
    [127, 0, "loopback"],
    [10, 0, "RFC1918 10/8"],
    [172, 16, "RFC1918 172.16/12 lower bound"],
    [172, 31, "RFC1918 172.16/12 upper bound"],
    [192, 168, "RFC1918 192.168/16"],
    [169, 254, "link-local"],
    [100, 64, "CGNAT lower bound"],
    [100, 127, "CGNAT upper bound"],
    [198, 18, "benchmarking lower bound"],
    [198, 19, "benchmarking upper bound"],
  ])("treats %d.%d.x.x (%s) as private", (a, b) => {
    expect(isPrivateIpv4Octets(a, b)).toBe(true);
  });

  it.each([
    [8, 8, "public DNS"],
    [1, 1, "public DNS"],
    [172, 15, "just below RFC1918 172.16/12"],
    [172, 32, "just above RFC1918 172.16/12"],
    [100, 63, "just below CGNAT"],
    [100, 128, "just above CGNAT"],
    [198, 17, "just below benchmarking"],
    [198, 20, "just above benchmarking"],
  ])("treats %d.%d.x.x (%s) as public", (a, b) => {
    expect(isPrivateIpv4Octets(a, b)).toBe(false);
  });
});

describe("isPrivateIpv6Literal", () => {
  it.each([
    ["::1", "loopback"],
    ["::", "unspecified"],
    ["::0", "unspecified"],
    ["fe80::1", "link-local"],
    ["feb0::1", "link-local upper bound"],
    ["fc00::1", "unique-local"],
    ["fd12:3456::1", "unique-local"],
    // URL#hostname normalizes ::ffff:127.0.0.1 to the hex-group form.
    ["::ffff:7f00:1", "IPv4-mapped loopback (hex-group form)"],
    ["::ffff:127.0.0.1", "IPv4-mapped loopback (dotted form)"],
    ["::ffff:c0a8:1", "IPv4-mapped 192.168.0.1 (hex-group form)"],
  ])("treats %s (%s) as private", (host) => {
    expect(isPrivateIpv6Literal(host)).toBe(true);
  });

  it.each([
    ["2001:db8::1", "documentation range"],
    ["2606:4700::1", "public (Cloudflare)"],
    ["::ffff:8.8.8.8", "IPv4-mapped public DNS (dotted form)"],
    ["::ffff:808:808", "IPv4-mapped 8.8.8.8 (hex-group form)"],
  ])("treats %s (%s) as public", (host) => {
    expect(isPrivateIpv6Literal(host)).toBe(false);
  });
});

describe("isPrivateHostname", () => {
  it.each([
    // loopback and localhost
    { hostname: "localhost", isPrivate: true },
    { hostname: "LOCALHOST", isPrivate: true },
    { hostname: "app.localhost", isPrivate: true },
    { hostname: "127.0.0.1", isPrivate: true },
    { hostname: "127.9.9.9", isPrivate: true },
    { hostname: "0.0.0.0", isPrivate: true },
    { hostname: "::1", isPrivate: true },
    { hostname: "[::1]", isPrivate: true },
    // RFC1918 / link-local / CGNAT
    { hostname: "10.0.0.5", isPrivate: true },
    { hostname: "172.16.0.1", isPrivate: true },
    { hostname: "172.31.255.255", isPrivate: true },
    { hostname: "192.168.1.10", isPrivate: true },
    { hostname: "169.254.1.1", isPrivate: true },
    { hostname: "100.64.0.1", isPrivate: true },
    { hostname: "100.101.102.103", isPrivate: true },
    // IPv6 private ranges
    { hostname: "fd12:3456:789a::1", isPrivate: true },
    { hostname: "fc00::1", isPrivate: true },
    { hostname: "fe80::1", isPrivate: true },
    { hostname: "::ffff:192.168.0.1", isPrivate: true },
    // private-looking names
    { hostname: "nas", isPrivate: true },
    { hostname: "grafana.local", isPrivate: true },
    { hostname: "vault.internal", isPrivate: true },
    { hostname: "printer.lan", isPrivate: true },
    { hostname: "server.home.arpa", isPrivate: true },
    { hostname: "router.home", isPrivate: true },
    { hostname: "machine.tailnet-1234.ts.net", isPrivate: true },
    { hostname: "example.com.", isPrivate: false },
    // public
    { hostname: "mcp.example.com", isPrivate: false },
    { hostname: "8.8.8.8", isPrivate: false },
    { hostname: "172.32.0.1", isPrivate: false },
    { hostname: "100.128.0.1", isPrivate: false },
    { hostname: "2606:4700::6810:84e5", isPrivate: false },
    { hostname: "::ffff:8.8.8.8", isPrivate: false },
    { hostname: "internal.example.com", isPrivate: false },
    { hostname: "localhost.example.com", isPrivate: false },
  ])("$hostname -> $isPrivate", ({ hostname, isPrivate }) => {
    expect(isPrivateHostname(hostname)).toBe(isPrivate);
  });
});

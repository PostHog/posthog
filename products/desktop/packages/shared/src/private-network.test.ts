import { describe, expect, it } from "vitest";
import { isPrivateIpv4Octets, isPrivateIpv6Literal } from "./private-network";

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

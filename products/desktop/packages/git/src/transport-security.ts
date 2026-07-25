// Zero-dependency git transport-hardening policy, shared by every seam in this
// package that shells out to `git`. Kept import-free (no simple-git, no node
// builtins) so both the simple-git client and the raw execFile/spawn seams can
// pull it in without dragging extra deps into their bundles.
//
// A repository's `.git/config` can point a remote at a URL such as
// `ext::sh -c "…"`. Git's `ext` transport runs that string as a shell command
// the next time a fetch/clone/ls-remote resolves the remote. Git's default for
// `protocol.ext` is `never`, so a bare `ext::` origin alone is refused with
// `fatal: transport 'ext' not allowed` and does not execute. The attack works
// because the attacker controls the delivered `.git/config` and can add
// `protocol.ext.allow=user` (or `always`) there too; then creating a
// task/worktree from that malicious folder or tarball triggers an automatic
// `git fetch` that resolves the remote and executes the command, which is remote
// code execution from untrusted repo contents.
//
// Denying `ext` closes that hole. Pinning `file` to `user` keeps user-initiated
// local-path clones working while still blocking them in submodule/recursive
// contexts. http/https/ssh are unaffected. These are passed as command-line
// config (`-c`), which overrides any value a malicious repo config tries to set.
//
// Passing these through simple-git needs `unsafe.allowUnsafeProtocolOverride`
// (see client.ts): it refuses every `protocol.*` config on a remote task without
// inspecting the value, so it blocks this hardening too.
export const GIT_TRANSPORT_SECURITY_CONFIG: readonly string[] = [
  "protocol.ext.allow=never",
  "protocol.file.allow=user",
];

/**
 * The same restrictions as `-c key=value` argv, for raw `git` subprocess seams
 * (execFile/spawn) that do not go through the simple-git client. Prepend to the
 * argument list so the flags precede the git subcommand.
 */
export function gitTransportSecurityArgs(): string[] {
  return GIT_TRANSPORT_SECURITY_CONFIG.flatMap((entry) => ["-c", entry]);
}

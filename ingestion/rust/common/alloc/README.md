# What is this?

We use jemalloc everywhere we can, for any binary that we expect to run in a long-lived process. The reason for this is that our workloads are:

- multi-threaded
- extremely prone to memory fragmentation (due to our heavy use of `serde_json`, or json generally)

jemalloc helps reduce memory fragmentation hugely, to the point of solving production OOMs that would have made use of capture-rs for replay a non-starter with the default system allocator.

At time of writing (2024-09-04), rust workspaces don't have good support for specifying dependencies on a per-target basis, so this crate does the work of pulling in jemalloc only when compiling for supported targets, and then exposes a simple macro to use jemalloc as the global allocator. Anyone writing a binary crate should put this macro at the top of their `main.rs`. Libraries should not make use of this crate.

## Future work

Functions could be added to this crate to, in situations where jemalloc is in use, report a set of metrics about the allocator, as well as other functionality (health/liveness, a way to specify hooks to execute when memory usage exceeds a certain threshold, etc). Right now, it's prety barebones.

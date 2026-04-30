// Library surface for the `funnels` crate. The production binary lives in
// `src/main.rs` and the bench harness lives in `src/bin/bench_io.rs`; both
// pull from this lib so the bench can build RBWNAT inputs using the same
// codec the binary uses.
#![allow(unstable_name_collisions)]

pub mod codec;
pub mod io;
pub mod parsing;
pub mod steps;
pub mod trends;
pub mod types;
pub mod unordered_steps;
pub mod unordered_trends;

pub use types::{Bytes, PropVal};

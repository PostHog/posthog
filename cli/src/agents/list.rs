use std::path::Path;

use anyhow::Result;
use colored::Colorize;

use crate::invocation_context::context;

use super::{discover_bundles, slug_of, ListArgs};

pub fn list_agents(args: &ListArgs) -> Result<()> {
    context().capture_command_invoked("agents_list");

    let bundles = discover_bundles(Path::new(&args.dir))?;

    println!();
    if bundles.is_empty() {
        println!("No agent bundles found under {}.", args.dir.bold());
        return Ok(());
    }

    println!("Agent bundles under {}:", args.dir.bold());
    println!();
    for b in &bundles {
        if let Some(slug) = slug_of(b) {
            println!("  {slug}");
        }
    }
    println!();
    println!(
        "{} bundle{} total.",
        bundles.len(),
        if bundles.len() == 1 { "" } else { "s" }
    );
    Ok(())
}

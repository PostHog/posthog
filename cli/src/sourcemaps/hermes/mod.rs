use clap::Subcommand;

pub use posthog_symbol_processing::sourcemaps::hermes::get_composed_map;

use crate::sourcemaps::inject::InjectArgs;

pub mod clone;
pub mod inject;
pub mod upload;

#[derive(Subcommand)]
pub enum HermesSubcommand {
    /// Inject your bundled chunk with a posthog chunk ID
    Inject(InjectArgs),
    /// Upload bundled Hermes source maps to PostHog
    Upload(upload::Args),
    /// Clone chunk_id and release_id metadata from bundle maps to composed maps
    Clone(clone::CloneArgs),
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::sourcemaps::args::ReleaseMode;
    use clap::Parser;

    #[derive(Parser)]
    struct HermesCli {
        #[command(subcommand)]
        command: HermesSubcommand,
    }

    fn parse(argv: &[&str]) -> HermesSubcommand {
        HermesCli::parse_from(argv).command
    }

    #[test]
    fn every_hermes_command_defaults_to_event_release_mode() {
        // A build that omits the flag must leave its maps release-independent, so two releases
        // shipping the same JavaScript keep one symbol set instead of colliding on whichever
        // release uploaded it first.
        let HermesSubcommand::Clone(clone) = parse(&[
            "hermes",
            "clone",
            "--minified-map-path",
            "main.jsbundle.map",
            "--composed-map-path",
            "main.jsbundle.hbc.composed.map",
        ]) else {
            panic!("expected the clone subcommand");
        };
        assert_eq!(clone.release_mode, ReleaseMode::Event);

        let HermesSubcommand::Upload(upload) = parse(&["hermes", "upload", "--directory", "dist"])
        else {
            panic!("expected the upload subcommand");
        };
        assert_eq!(upload.release_mode, ReleaseMode::Event);

        // `hermes inject` shares InjectArgs with `sourcemap inject`, so it takes the same default.
        let HermesSubcommand::Inject(inject) = parse(&["hermes", "inject", "--directory", "dist"])
        else {
            panic!("expected the inject subcommand");
        };
        assert_eq!(inject.release_mode, ReleaseMode::Event);
    }

    #[test]
    fn every_hermes_command_accepts_symbol_set_release_mode() {
        let HermesSubcommand::Clone(clone) = parse(&[
            "hermes",
            "clone",
            "--minified-map-path",
            "main.jsbundle.map",
            "--composed-map-path",
            "main.jsbundle.hbc.composed.map",
            "--release-mode",
            "symbol-set",
        ]) else {
            panic!("expected the clone subcommand");
        };
        assert_eq!(clone.release_mode, ReleaseMode::SymbolSet);

        let HermesSubcommand::Upload(upload) = parse(&[
            "hermes",
            "upload",
            "--directory",
            "dist",
            "--release-mode",
            "symbol-set",
        ]) else {
            panic!("expected the upload subcommand");
        };
        assert_eq!(upload.release_mode, ReleaseMode::SymbolSet);

        let HermesSubcommand::Inject(inject) = parse(&[
            "hermes",
            "inject",
            "--directory",
            "dist",
            "--release-mode",
            "symbol-set",
        ]) else {
            panic!("expected the inject subcommand");
        };
        assert_eq!(inject.release_mode, ReleaseMode::SymbolSet);
    }
}

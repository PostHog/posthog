use anyhow::Error;
use clap::Subcommand;
use miette::{Diagnostic, SourceSpan};

use crate::{
    tui::query::start_query_editor,
    utils::{
        auth::load_token,
        posthog::capture_command_invoked,
        query::{check_query, run_query, MetadataResponse, Notice},
    },
};

#[derive(Debug, Subcommand)]
pub enum QueryCommand {
    /// Start the interactive query editor
    Editor {
        #[arg(long, default_value = "false")]
        /// Don't print the final query to stdout
        no_print: bool,
        #[arg(long, default_value = "false")]
        /// Print out query debug information, as well as showing query results
        debug: bool,
        #[arg(long, default_value = "false")]
        /// Run the final query and print the results as json lines to stdout
        execute: bool,
    },
    /// Run a query directly, and print the results as json lines to stdout
    Run {
        /// The query to run
        query: String,
        #[arg(long)]
        /// Print the returned json, rather than just the results
        debug: bool,
    },
    /// Syntax and type-check a query, without running it
    Check {
        /// The query to check
        query: String,
        /// Print the raw response from the server as json
        #[arg(long)]
        raw: bool,
    },
}

pub fn query_command(host: Option<String>, query: &QueryCommand) -> Result<(), Error> {
    let creds = load_token()?;
    let host = creds.get_host(host.as_deref());

    match query {
        QueryCommand::Editor {
            no_print,
            debug,
            execute,
        } => {
            // Given this is an interactive command, we're happy enough to not join the capture handle
            let handle = capture_command_invoked("query_editor", Some(creds.env_id.clone()));
            let res = start_query_editor(&host, creds.clone(), *debug)?;
            if !no_print {
                println!("Final query: {res}");
            }
            if *execute {
                let query_endpoint = format!("{}/api/environments/{}/query", host, creds.env_id);
                let res = run_query(&query_endpoint, &creds.token, &res)??;
                for result in res.results {
                    println!("{}", serde_json::to_string(&result)?);
                }
            }
            let _ = handle.join();
        }
        QueryCommand::Run { query, debug } => {
            // Given this is an interactive command, we're happy enough to not join the capture handle
            let handle = capture_command_invoked("query_run", Some(creds.env_id.clone()));
            let query_endpoint = format!("{}/api/environments/{}/query", host, creds.env_id);
            let res = run_query(&query_endpoint, &creds.token, query)??;
            if *debug {
                println!("{}", serde_json::to_string_pretty(&res)?);
            } else {
                for result in res.results {
                    println!("{}", serde_json::to_string(&result)?);
                }
            }
            let _ = handle.join();
        }
        QueryCommand::Check { query, raw } => {
            let handle = capture_command_invoked("query_check", Some(creds.env_id.clone()));
            let query_endpoint = format!("{}/api/environments/{}/query", host, creds.env_id);
            let res = check_query(&query_endpoint, &creds.token, query)?;
            if *raw {
                println!("{}", serde_json::to_string_pretty(&res)?);
            } else {
                pretty_print_check_response(query, res)?;
            }
            let _ = handle.join();
        }
    }

    Ok(())
}

#[derive(thiserror::Error, Debug, Diagnostic)]
#[error("Query checked")]
#[diagnostic()]
struct CheckDiagnostic {
    #[source_code]
    source_code: String,

    #[related]
    errors: Vec<CheckError>,
    #[related]
    warnings: Vec<CheckWarning>,
    #[related]
    notices: Vec<CheckNotice>,
}

#[derive(thiserror::Error, Debug, Diagnostic)]
#[error("Error")]
#[diagnostic(severity(Error))]
struct CheckError {
    #[help]
    message: String,
    #[label]
    err_span: SourceSpan,
}

#[derive(thiserror::Error, Debug, Diagnostic)]
#[error("Warning")]
#[diagnostic(severity(Warning))]
struct CheckWarning {
    #[help]
    message: String,
    #[label]
    err_span: SourceSpan,
}

#[derive(thiserror::Error, Debug, Diagnostic)]
#[error("Notice")]
#[diagnostic(severity(Info))]
struct CheckNotice {
    #[help]
    message: String,
    #[label]
    err_span: SourceSpan,
}

// We use miette to pretty print notices, warnings and errors across the original query.
fn pretty_print_check_response(query: &str, res: MetadataResponse) -> Result<(), Error> {
    let errors = res.errors.into_iter().map(CheckError::from).collect();
    let warnings = res.warnings.into_iter().map(CheckWarning::from).collect();
    let notices = res.notices.into_iter().map(CheckNotice::from).collect();

    let diagnostic: miette::Error = CheckDiagnostic {
        source_code: query.to_string(),
        errors,
        warnings,
        notices,
    }
    .into();

    println!("{diagnostic:?}");

    Ok(())
}

impl From<Notice> for CheckNotice {
    fn from(notice: Notice) -> Self {
        let (start, len) = match notice.span {
            Some(span) => (span.start, span.end - span.start),
            None => (0, 0),
        };
        Self {
            message: notice.message,
            err_span: SourceSpan::new(start.into(), len),
        }
    }
}

impl From<Notice> for CheckWarning {
    fn from(notice: Notice) -> Self {
        let (start, len) = match notice.span {
            Some(span) => (span.start, span.end - span.start),
            None => (0, 0),
        };
        Self {
            message: notice.message,
            err_span: SourceSpan::new(start.into(), len),
        }
    }
}

impl From<Notice> for CheckError {
    fn from(notice: Notice) -> Self {
        let (start, len) = match notice.span {
            Some(span) => (span.start, span.end - span.start),
            None => (0, 0),
        };
        Self {
            message: notice.message,
            err_span: SourceSpan::new(start.into(), len),
        }
    }
}

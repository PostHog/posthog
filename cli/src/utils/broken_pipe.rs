use std::io::{self, Write};

use tracing_subscriber::fmt::MakeWriter;

/// A writer that drops broken-pipe errors instead of surfacing them.
///
/// Rust ignores `SIGPIPE` at startup, so writing to a pipe whose reader has
/// gone away (a CI log collector exiting, `| head`, a closed terminal) fails
/// with `ErrorKind::BrokenPipe` rather than ending the process. The std
/// `print!`/`eprintln!` machinery and the tracing subscriber both panic on
/// that write error, which aborts the whole command — a sourcemap upload logs
/// once per batch, so a single dropped pipe kills an upload mid-run. Swallowing
/// the error restores the graceful behavior a default `SIGPIPE` would give.
pub struct IgnoreBrokenPipe<W>(pub W);

impl<W: Write> Write for IgnoreBrokenPipe<W> {
    fn write(&mut self, buf: &[u8]) -> io::Result<usize> {
        match self.0.write(buf) {
            Err(e) if e.kind() == io::ErrorKind::BrokenPipe => Ok(buf.len()),
            other => other,
        }
    }

    fn flush(&mut self) -> io::Result<()> {
        match self.0.flush() {
            Err(e) if e.kind() == io::ErrorKind::BrokenPipe => Ok(()),
            other => other,
        }
    }
}

/// `MakeWriter` for the tracing subscriber that writes to stderr while dropping
/// broken-pipe errors, so per-batch upload logs can never abort the command.
#[derive(Clone, Default)]
pub struct BrokenPipeSafeStderr;

impl<'a> MakeWriter<'a> for BrokenPipeSafeStderr {
    type Writer = IgnoreBrokenPipe<io::Stderr>;

    fn make_writer(&'a self) -> Self::Writer {
        IgnoreBrokenPipe(io::stderr())
    }
}

/// Backs [`safe_eprintln!`]. Writes a line to stderr, dropping a broken pipe.
pub fn write_stderr_line(args: std::fmt::Arguments<'_>) {
    write_line(IgnoreBrokenPipe(io::stderr()), args, "stderr");
}

/// Backs [`safe_println!`]. Writes a line to stdout, dropping a broken pipe.
pub fn write_stdout_line(args: std::fmt::Arguments<'_>) {
    write_line(IgnoreBrokenPipe(io::stdout()), args, "stdout");
}

/// Writes one line, dropping a broken pipe but panicking on any other write
/// error. A real failure such as a full disk must surface the way the std
/// `println!`/`eprintln!` macros would, so the command does not report success
/// after failing to emit its output.
fn write_line<W: Write>(mut writer: W, args: std::fmt::Arguments<'_>, target: &str) {
    if let Err(e) = writeln!(writer, "{args}") {
        panic!("failed printing to {target}: {e}");
    }
}

/// `eprintln!` that drops broken-pipe errors instead of panicking.
#[macro_export]
macro_rules! safe_eprintln {
    () => { $crate::utils::broken_pipe::write_stderr_line(::std::format_args!("")) };
    ($($arg:tt)*) => { $crate::utils::broken_pipe::write_stderr_line(::std::format_args!($($arg)*)) };
}

/// `println!` that drops broken-pipe errors instead of panicking.
#[macro_export]
macro_rules! safe_println {
    () => { $crate::utils::broken_pipe::write_stdout_line(::std::format_args!("")) };
    ($($arg:tt)*) => { $crate::utils::broken_pipe::write_stdout_line(::std::format_args!($($arg)*)) };
}

#[cfg(test)]
mod tests {
    use super::*;

    struct FailingWriter(io::ErrorKind);

    impl Write for FailingWriter {
        fn write(&mut self, _buf: &[u8]) -> io::Result<usize> {
            Err(io::Error::new(self.0, "boom"))
        }

        fn flush(&mut self) -> io::Result<()> {
            Err(io::Error::new(self.0, "boom"))
        }
    }

    #[test]
    fn broken_pipe_writes_are_dropped() {
        let mut writer = IgnoreBrokenPipe(FailingWriter(io::ErrorKind::BrokenPipe));
        assert_eq!(writer.write(b"hello").unwrap(), 5);
        writer.flush().unwrap();
    }

    #[test]
    fn other_errors_still_propagate() {
        let mut writer = IgnoreBrokenPipe(FailingWriter(io::ErrorKind::PermissionDenied));
        assert_eq!(
            writer.write(b"hello").unwrap_err().kind(),
            io::ErrorKind::PermissionDenied
        );
        assert_eq!(
            writer.flush().unwrap_err().kind(),
            io::ErrorKind::PermissionDenied
        );
    }

    #[test]
    fn write_line_drops_broken_pipe() {
        write_line(
            IgnoreBrokenPipe(FailingWriter(io::ErrorKind::BrokenPipe)),
            format_args!("hello"),
            "test",
        );
    }

    #[test]
    #[should_panic(expected = "failed printing to test")]
    fn write_line_panics_on_other_errors() {
        write_line(
            IgnoreBrokenPipe(FailingWriter(io::ErrorKind::PermissionDenied)),
            format_args!("hello"),
            "test",
        );
    }
}

// File reads whose failures read the way they did when hog read the files itself with Bun, because
// hog shows these messages to people and scripts match on them.

use std::{fs, io, path::Path};

// Bun's message for a `TextDecoder` in fatal mode that meets a byte sequence that is not UTF-8.
const INVALID_UTF8: &str = "The encoded data was not valid for encoding utf-8";

// The error codes a build folder produces in practice, with libuv's description of each.
#[cfg(unix)]
const DESCRIPTIONS: [(i32, &str, &str); 12] = [
    (libc::ENOENT, "ENOENT", "no such file or directory"),
    (libc::EACCES, "EACCES", "permission denied"),
    (libc::EPERM, "EPERM", "operation not permitted"),
    (libc::EISDIR, "EISDIR", "illegal operation on a directory"),
    (libc::ENOTDIR, "ENOTDIR", "not a directory"),
    (libc::EEXIST, "EEXIST", "file already exists"),
    (libc::ENOSPC, "ENOSPC", "no space left on device"),
    (libc::EROFS, "EROFS", "read-only file system"),
    (libc::EMFILE, "EMFILE", "too many open files"),
    (libc::ELOOP, "ELOOP", "too many symbolic links encountered"),
    (libc::ENAMETOOLONG, "ENAMETOOLONG", "name too long"),
    (libc::EBUSY, "EBUSY", "resource busy or locked"),
];

// `ENOENT: no such file or directory, open '/build/a.js'`. An error outside the table keeps the
// operating system's own text.
#[cfg(unix)]
pub fn message(error: &io::Error, syscall: &str, path: &Path) -> String {
    let known = DESCRIPTIONS
        .iter()
        .find(|(code, _, _)| error.raw_os_error() == Some(*code));

    match known {
        // Reading a folder fails in `read`, after the open worked, and Bun names no path there.
        Some((code, name, description)) if *code == libc::EISDIR => {
            format!("{name}: {description}, read")
        }
        Some((_, name, description)) => {
            format!("{name}: {description}, {syscall} '{}'", path.display())
        }
        None => format!("{error}, {syscall} '{}'", path.display()),
    }
}

#[cfg(not(unix))]
pub fn message(error: &io::Error, syscall: &str, path: &Path) -> String {
    format!("{error}, {syscall} '{}'", path.display())
}

// `EACCES: permission denied, rename '/build/a.map' -> '/build/a.map.bak'`.
pub fn rename_message(error: &io::Error, from: &Path, to: &Path) -> String {
    format!("{} -> '{}'", message(error, "rename", from), to.display())
}

pub fn utf8(bytes: Vec<u8>) -> Result<String, String> {
    String::from_utf8(bytes).map_err(|_| INVALID_UTF8.to_string())
}

pub fn read(path: &Path) -> Result<Vec<u8>, String> {
    fs::read(path).map_err(|error| message(&error, "open", path))
}

// A byte order mark stays in the text, as it does for hog's sourcemap reader.
pub fn read_text(path: &Path) -> Result<String, String> {
    utf8(read(path)?)
}

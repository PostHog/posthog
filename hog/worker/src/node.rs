// Read failures carry Bun's messages, because hog shows them to people and scripts match on them.

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

pub fn read(path: &Path) -> Result<Vec<u8>, String> {
    fs::read(path).map_err(|error| message(&error, "open", path))
}

pub fn read_text(path: &Path) -> Result<String, String> {
    String::from_utf8(read(path)?).map_err(|_| INVALID_UTF8.to_string())
}

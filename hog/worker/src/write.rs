// Replaces a set of files so that either all of them change or none does, because a bundle
// injected while its map keeps the old offsets can't be repaired by running again.

use rayon::prelude::*;
use std::{
    collections::HashSet,
    fs,
    io::{self, Write},
    path::{Path, PathBuf},
};

use crate::{node, trace::Trace};

const TEMPORARY_SUFFIX: &str = "tmp";
const BACKUP_SUFFIX: &str = "bak";

pub struct Staged {
    temporary: PathBuf,
    target: PathBuf,
}

fn sibling_name(target: &Path, suffix: &str) -> PathBuf {
    let mut name = target.as_os_str().to_owned();
    name.push(format!(".{}.{suffix}", uuid::Uuid::new_v4()));
    PathBuf::from(name)
}

// A rename replaces a read-only file, where writing to it would have failed.
#[cfg(unix)]
fn check_writable(target: &Path) -> io::Result<()> {
    use std::{ffi::CString, os::unix::ffi::OsStrExt};

    let path = CString::new(target.as_os_str().as_bytes())?;
    // SAFETY: the path is a valid NUL-terminated string for the duration of the call.
    if unsafe { libc::access(path.as_ptr(), libc::W_OK) } == 0 {
        Ok(())
    } else {
        Err(io::Error::last_os_error())
    }
}

#[cfg(not(unix))]
fn check_writable(target: &Path) -> io::Result<()> {
    if fs::metadata(target)?.permissions().readonly() {
        return Err(io::ErrorKind::PermissionDenied.into());
    }
    Ok(())
}

pub fn stage(path: &Path, contents: &[u8]) -> Result<Staged, String> {
    let target = dunce::canonicalize(path).map_err(|error| node::message(&error, "lstat", path))?;
    check_writable(&target).map_err(|error| node::message(&error, "access", &target))?;
    let permissions = fs::metadata(&target)
        .map_err(|error| node::message(&error, "stat", &target))?
        .permissions();

    let temporary = sibling_name(&target, TEMPORARY_SUFFIX);
    let written = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temporary)
        .and_then(|mut file| file.write_all(contents))
        .and_then(|_| fs::set_permissions(&temporary, permissions));
    if let Err(error) = written {
        let _ = fs::remove_file(&temporary);
        return Err(node::message(&error, "open", &temporary));
    }

    Ok(Staged { temporary, target })
}

pub fn discard(staged: &[Staged]) {
    staged.par_iter().for_each(|file| {
        let _ = fs::remove_file(&file.temporary);
    });
}

// Where the file system can swap two paths in one call, each staged file trades places with its
// target, so the staged path holds the old contents and a failure swaps them back. When two
// bundles share a map, the files go in order, so the last pair wins. Otherwise they go in
// parallel, because a large build waits on one metadata operation per file.
pub fn commit(staged: Vec<Staged>, trace: &Trace) -> Result<(), String> {
    let Some(first) = staged.first() else {
        return Ok(());
    };
    match swap(&first.temporary, &first.target) {
        Ok(()) => {}
        Err(error) if is_unsupported(&error) => return commit_with_backups(staged, trace),
        Err(error) => {
            discard(&staged);
            return Err(node::message(&error, "rename", &first.target));
        }
    }

    let rest = &staged[1..];
    let swap_one = |file: &Staged| swap(&file.temporary, &file.target);
    let swapped: Vec<io::Result<()>> = if has_shared_targets(&staged) {
        let mut swapped = Vec::with_capacity(rest.len());
        for file in rest {
            let result = swap_one(file);
            let failed = result.is_err();
            swapped.push(result);
            if failed {
                break;
            }
        }
        swapped
    } else {
        rest.par_iter().map(swap_one).collect()
    };
    trace.mark("commit: swap");

    if let Some(failed) = swapped.iter().position(Result::is_err) {
        let target = rest[failed].target.clone();
        // Back in reverse order, so a shared target ends with its first, original contents.
        let done: Vec<&Staged> = std::iter::once(first)
            .chain(
                rest.iter()
                    .zip(&swapped)
                    .filter(|(_, result)| result.is_ok())
                    .map(|(file, _)| file),
            )
            .collect();
        for file in done.iter().rev() {
            let _ = swap(&file.temporary, &file.target);
        }
        discard(&staged);

        let error = swapped.into_iter().nth(failed).and_then(Result::err);
        return Err(error.map_or_else(
            || format!("hog-worker couldn't replace {}", target.display()),
            |error| node::message(&error, "rename", &target),
        ));
    }

    discard(&staged);
    trace.mark("commit: clean up");
    Ok(())
}

fn has_shared_targets(staged: &[Staged]) -> bool {
    let mut seen = HashSet::new();
    !staged.iter().all(|file| seen.insert(&file.target))
}

#[cfg(unix)]
fn is_unsupported(error: &io::Error) -> bool {
    const UNSUPPORTED: [i32; 3] = [libc::EINVAL, libc::ENOTSUP, libc::ENOSYS];

    matches!(error.kind(), io::ErrorKind::Unsupported)
        || error
            .raw_os_error()
            .is_some_and(|code| UNSUPPORTED.contains(&code))
}

#[cfg(not(unix))]
fn is_unsupported(error: &io::Error) -> bool {
    matches!(error.kind(), io::ErrorKind::Unsupported)
}

#[cfg(target_os = "macos")]
fn swap(a: &Path, b: &Path) -> io::Result<()> {
    use std::{ffi::CString, os::unix::ffi::OsStrExt};

    let a = CString::new(a.as_os_str().as_bytes())?;
    let b = CString::new(b.as_os_str().as_bytes())?;
    // SAFETY: both are valid NUL-terminated paths for the duration of the call.
    if unsafe { libc::renamex_np(a.as_ptr(), b.as_ptr(), libc::RENAME_SWAP) } == 0 {
        Ok(())
    } else {
        Err(io::Error::last_os_error())
    }
}

#[cfg(target_os = "linux")]
fn swap(a: &Path, b: &Path) -> io::Result<()> {
    use std::{ffi::CString, os::unix::ffi::OsStrExt};

    let a = CString::new(a.as_os_str().as_bytes())?;
    let b = CString::new(b.as_os_str().as_bytes())?;
    // SAFETY: both are valid NUL-terminated paths for the duration of the call. The raw syscall
    // also works on a libc without a renameat2 wrapper, such as an old musl.
    let result = unsafe {
        libc::syscall(
            libc::SYS_renameat2,
            libc::AT_FDCWD,
            a.as_ptr(),
            libc::AT_FDCWD,
            b.as_ptr(),
            libc::RENAME_EXCHANGE,
        )
    };
    if result == 0 {
        Ok(())
    } else {
        Err(io::Error::last_os_error())
    }
}

#[cfg(not(any(target_os = "macos", target_os = "linux")))]
fn swap(_: &Path, _: &Path) -> io::Result<()> {
    Err(io::ErrorKind::Unsupported.into())
}

// Each target is first hard-linked to a backup, so a failed rename puts every target back without
// holding the old contents in memory.
fn commit_with_backups(staged: Vec<Staged>, trace: &Trace) -> Result<(), String> {
    let mut seen = HashSet::new();
    let unique: Vec<&PathBuf> = staged
        .iter()
        .map(|file| &file.target)
        .filter(|target| seen.insert(*target))
        .collect();
    let shared = unique.len() != staged.len();
    let backups: Vec<(PathBuf, PathBuf)> = unique
        .par_iter()
        .map(|target| (sibling_name(target, BACKUP_SUFFIX), (*target).clone()))
        .collect();

    let rename = |file: &Staged| {
        fs::rename(&file.temporary, &file.target)
            .map_err(|error| node::message(&error, "rename", &file.target))
    };
    let result = backups
        .par_iter()
        .try_for_each(|(backup, target)| {
            fs::hard_link(target, backup)
                .or_else(|_| fs::copy(target, backup).map(|_| ()))
                .map_err(|error| node::message(&error, "link", target))
        })
        .and_then(|_| {
            trace.mark("commit: back up");
            if shared {
                staged.iter().try_for_each(rename)
            } else {
                staged.par_iter().try_for_each(rename)
            }
        });
    trace.mark("commit: rename");

    if result.is_err() {
        // Renaming a backup over a target that still links the same file leaves the backup, so
        // the backups are removed after.
        backups.par_iter().for_each(|(backup, target)| {
            let _ = fs::rename(backup, target);
        });
        discard(&staged);
    }
    backups.par_iter().for_each(|(backup, _)| {
        let _ = fs::remove_file(backup);
    });
    trace.mark("commit: clean up");

    result
}

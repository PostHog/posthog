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
#[cfg(unix)]
const PRIVATE_MODE: u32 = 0o600;

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

// Owner-only until the target's permissions are copied over, so a map the owner keeps private is
// never readable by others while it is written.
#[cfg(unix)]
fn create_private(path: &Path) -> io::Result<fs::File> {
    use std::os::unix::fs::OpenOptionsExt;

    fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(PRIVATE_MODE)
        .open(path)
}

#[cfg(not(unix))]
fn create_private(path: &Path) -> io::Result<fs::File> {
    fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
}

pub fn stage(path: &Path, contents: &[u8]) -> Result<Staged, String> {
    let target = dunce::canonicalize(path).map_err(|error| node::message(&error, "lstat", path))?;
    check_writable(&target).map_err(|error| node::message(&error, "access", &target))?;
    let permissions = fs::metadata(&target)
        .map_err(|error| node::message(&error, "stat", &target))?
        .permissions();

    let temporary = sibling_name(&target, TEMPORARY_SUFFIX);
    let written = create_private(&temporary)
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
        // A target on a file system that can't swap, such as a second mount, falls back to backups.
        let unsupported = swapped
            .iter()
            .any(|result| result.as_ref().is_err_and(is_unsupported));
        // Back in reverse order, so a shared target ends with its first, original contents. A
        // staged path that could not swap back still holds the original, so it is kept.
        let done: Vec<&Staged> = std::iter::once(first)
            .chain(
                rest.iter()
                    .zip(&swapped)
                    .filter(|(_, result)| result.is_ok())
                    .map(|(file, _)| file),
            )
            .collect();
        let stranded: Vec<&Staged> = done
            .into_iter()
            .rev()
            .filter(|file| swap(&file.temporary, &file.target).is_err())
            .collect();
        if stranded.is_empty() && unsupported {
            return commit_with_backups(staged, trace);
        }
        let kept: HashSet<&PathBuf> = stranded.iter().map(|file| &file.temporary).collect();
        discard_except(&staged, &kept);

        let error = swapped.into_iter().nth(failed).and_then(Result::err);
        let message = error.map_or_else(
            || format!("hog-worker couldn't replace {}", target.display()),
            |error| node::message(&error, "rename", &target),
        );
        let stranded = stranded.iter().map(|file| (&file.target, &file.temporary));
        return Err(with_stranded(message, stranded));
    }

    discard(&staged);
    trace.mark("commit: clean up");
    Ok(())
}

fn discard_except(staged: &[Staged], kept: &HashSet<&PathBuf>) {
    staged
        .par_iter()
        .filter(|file| !kept.contains(&file.temporary))
        .for_each(|file| {
            let _ = fs::remove_file(&file.temporary);
        });
}

// Names each file that could not be put back and the path that still holds its original contents.
fn with_stranded<'a>(
    message: String,
    stranded: impl Iterator<Item = (&'a PathBuf, &'a PathBuf)>,
) -> String {
    stranded.fold(message, |message, (target, original)| {
        format!(
            "{message}. {} couldn't be restored, and its original contents are in {}",
            target.display(),
            original.display()
        )
    })
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

// Each target is first hard-linked to a backup, so a failed rename puts the replaced targets back
// without holding the old contents in memory.
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

    let backed_up: Vec<Result<(), String>> = backups
        .par_iter()
        .map(|(backup, target)| {
            fs::hard_link(target, backup)
                .or_else(|_| fs::copy(target, backup).map(|_| ()))
                .map_err(|error| node::message(&error, "link", target))
        })
        .collect();
    // No target changed yet, so every backup goes, including one a failed copy left cut short.
    if let Some(message) = backed_up.into_iter().find_map(Result::err) {
        remove_backups(&backups, &HashSet::new());
        discard(&staged);
        return Err(message);
    }
    trace.mark("commit: back up");

    let rename = |file: &Staged| {
        fs::rename(&file.temporary, &file.target)
            .map_err(|error| node::message(&error, "rename", &file.target))
    };
    let renamed: Vec<Result<(), String>> = if shared {
        let mut renamed = Vec::with_capacity(staged.len());
        for file in &staged {
            let result = rename(file);
            let failed = result.is_err();
            renamed.push(result);
            if failed {
                break;
            }
        }
        renamed
    } else {
        staged.par_iter().map(rename).collect()
    };
    trace.mark("commit: rename");

    let Some(message) = renamed.iter().find_map(|result| result.clone().err()) else {
        remove_backups(&backups, &HashSet::new());
        trace.mark("commit: clean up");
        return Ok(());
    };

    // Only the targets a rename replaced go back. A backup that can't be put back still holds the
    // original, so it stays.
    let replaced: HashSet<&PathBuf> = staged
        .iter()
        .zip(&renamed)
        .filter(|(_, result)| result.is_ok())
        .map(|(file, _)| &file.target)
        .collect();
    let stranded: Vec<&(PathBuf, PathBuf)> = backups
        .iter()
        .filter(|(backup, target)| replaced.contains(target) && fs::rename(backup, target).is_err())
        .collect();
    let kept: HashSet<&PathBuf> = stranded.iter().map(|(backup, _)| backup).collect();
    remove_backups(&backups, &kept);
    discard(&staged);
    trace.mark("commit: clean up");

    Err(with_stranded(
        message,
        stranded.iter().map(|(backup, target)| (target, backup)),
    ))
}

fn remove_backups(backups: &[(PathBuf, PathBuf)], kept: &HashSet<&PathBuf>) {
    backups
        .par_iter()
        .filter(|(backup, _)| !kept.contains(backup))
        .for_each(|(backup, _)| {
            let _ = fs::remove_file(backup);
        });
}

#[cfg(test)]
mod tests {
    use super::*;

    fn scratch() -> PathBuf {
        let folder =
            std::env::temp_dir().join(format!("hog-worker-write-{}", uuid::Uuid::new_v4()));
        fs::create_dir(&folder).expect("the scratch folder is created");
        folder
    }

    #[test]
    fn a_failed_rename_puts_back_what_was_replaced_and_leaves_no_files() {
        let folder = scratch();
        let bundle = folder.join("app.js");
        let map = folder.join("app.js.map");
        fs::write(&bundle, "original").unwrap();
        fs::write(&map, "original map").unwrap();
        // A staged file that is gone makes its rename fail after the backups and the other rename.
        let staged = vec![
            stage(&bundle, b"injected").unwrap(),
            Staged {
                temporary: sibling_name(&map, TEMPORARY_SUFFIX),
                target: map.clone(),
            },
        ];

        let result = commit_with_backups(staged, &Trace::from_environment());

        assert!(result.is_err());
        assert_eq!(fs::read_to_string(&bundle).unwrap(), "original");
        assert_eq!(fs::read_to_string(&map).unwrap(), "original map");
        let mut left: Vec<String> = fs::read_dir(&folder)
            .unwrap()
            .map(|entry| entry.unwrap().file_name().to_string_lossy().into_owned())
            .collect();
        left.sort();
        assert_eq!(left, ["app.js", "app.js.map"]);
        fs::remove_dir_all(folder).unwrap();
    }
}

// Rewriting a map allocates several copies of it for a moment. glibc keeps freed blocks for reuse,
// and with one arena per thread that more than doubles the memory a large build needs, so large
// blocks go back to the operating system as soon as they are freed.

#[cfg(all(target_os = "linux", target_env = "gnu"))]
const MMAP_THRESHOLD_BYTES: libc::c_int = 256 * 1024;
#[cfg(all(target_os = "linux", target_env = "gnu"))]
const TRIM_THRESHOLD_BYTES: libc::c_int = 64 * 1024;

#[cfg(all(target_os = "linux", target_env = "gnu"))]
pub fn tune_allocator() {
    // SAFETY: mallopt only sets allocator parameters, and runs here before any other thread exists.
    unsafe {
        libc::mallopt(libc::M_MMAP_THRESHOLD, MMAP_THRESHOLD_BYTES);
        libc::mallopt(libc::M_TRIM_THRESHOLD, TRIM_THRESHOLD_BYTES);
    }
}

#[cfg(not(all(target_os = "linux", target_env = "gnu")))]
pub fn tune_allocator() {}

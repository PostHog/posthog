// Cloud task log history for the web host.
//
// A cloud task's authoritative transcript is persisted to object storage; the
// backend hands out a pre-signed `log_url`. SessionService.fetchSessionLogs
// tries a local on-disk cache first (none on web) then falls back to
// logs.fetchS3Logs(logUrl). Desktop's implementation is a plain unauthenticated
// fetch of that URL (LocalLogsService.fetchS3Logs) — fully portable, so web does
// the same. The local-cache methods are no-ops here (no durable disk to cache
// to across page loads).
//
// One browser-specific caveat: unlike Node, a browser fetch of the pre-signed
// URL is subject to the bucket/CDN CORS policy. If that blocks it, the fetch
// rejects (TypeError) and history stays empty — logged distinctly so it's
// diagnosable rather than silent.

export async function fetchS3Logs(logUrl: string): Promise<string | null> {
  try {
    const response = await fetch(logUrl);
    if (!response.ok) return null;
    return await response.text();
  } catch (error) {
    // A CORS rejection surfaces here as a TypeError with no response.
    console.warn(
      "[web-logs] Failed to fetch cloud log history (possible CORS on the pre-signed URL)",
      error,
    );
    return null;
  }
}

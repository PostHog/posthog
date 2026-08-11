// Ask the browser to make this origin's storage "persistent" — exempt from
// automatic eviction under storage pressure (the common accidental-loss case
// for the localStorage-backed per-device stores: cloud-workspace map, archived
// tasks, pins/timestamps). Browsers grant this based on engagement/installation
// signals; it is best-effort.
//
// This does NOT protect against a user manually clearing site data — that path
// wipes persistent storage too. Durable, cross-device state (e.g. archive)
// ultimately needs a server-side field; this only hardens the everyday case.
export async function requestPersistentStorage(
  log: (message: string, ...args: unknown[]) => void,
): Promise<void> {
  try {
    if (!navigator.storage?.persist) return;
    if (await navigator.storage.persisted()) return; // already granted
    const granted = await navigator.storage.persist();
    log(
      granted
        ? "Persistent storage granted"
        : "Persistent storage denied (per-device state may be evicted under storage pressure)",
    );
  } catch (error) {
    log("Failed to request persistent storage", error);
  }
}

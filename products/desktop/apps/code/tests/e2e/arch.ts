// The x64 app is built and smoke tested on an Apple silicon runner, so it runs
// under Rosetta. Translation makes each launch roughly ten times slower than a
// native one, and the first launch of the run is slower still.
export const isTranslated =
  process.platform === "darwin" &&
  !!process.env.E2E_APP_ARCH &&
  process.env.E2E_APP_ARCH !== process.arch;

export const firstRenderTimeout = isTranslated ? 90000 : 30000;

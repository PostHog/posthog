// Every plain object, array and function in the process inherits from these prototypes. A path walker that
// follows `__proto__` or `constructor.prototype` from user input can add a key to one of them, and every
// object in the process then inherits that key, which corrupts unrelated work (prom-client rejects every
// labelled metric call, for example). Sealing makes that write throw a TypeError in strict-mode code, so it
// fails inside the call that made it.
//
// Seal, not freeze: a frozen prototype makes inherited properties such as `toString` read-only, and
// dependencies that assign their own `toString` or `constructor` on an instance then throw at load.
//
// This module must be the first import of the plugin server entrypoint (src/index.ts), so that no dependency
// runs before the seal. Other processes, such as the recording rasterizer and worker threads, have their own
// unsealed intrinsics. String, Number and Boolean prototypes also stay open, so path walkers still need
// own-property guards. Set SEAL_INTRINSICS=false to turn it off.
export const SEALED_PROTOTYPES: readonly object[] = [Object.prototype, Array.prototype, Function.prototype]

if (process.env.SEAL_INTRINSICS !== 'false') {
    for (const prototype of SEALED_PROTOTYPES) {
        Object.seal(prototype)
    }
}

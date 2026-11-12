// A key added to one of these prototypes through `__proto__` or `constructor.prototype` is inherited by every
// object in the process. Sealing makes that write throw a TypeError in strict-mode code, inside the call that
// made it. Seal, not freeze: a frozen prototype makes inherited properties such as `toString` read-only, and
// dependencies that assign their own `toString` on an instance then throw at load.
export const SEALED_PROTOTYPES: readonly object[] = [Object.prototype, Array.prototype, Function.prototype]

if (process.env.SEAL_INTRINSICS !== 'false') {
    for (const prototype of SEALED_PROTOTYPES) {
        Object.seal(prototype)
    }
}

// esbuild takes its target from tsconfig and downlevels syntax only, never built-ins, so
// `Object.hasOwn` reaches Chromium 92 and older as a TypeError while the app entry evaluates.
if (typeof Object.hasOwn !== 'function') {
    Object.defineProperty(Object, 'hasOwn', {
        value: function hasOwn(target: object, property: PropertyKey): boolean {
            return Object.prototype.hasOwnProperty.call(target, property)
        },
        writable: true,
        configurable: true,
    })
}

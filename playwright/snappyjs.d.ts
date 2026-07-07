declare module 'snappyjs' {
    export function compress(input: Uint8Array | ArrayBuffer | Buffer): Uint8Array
    export function uncompress(compressed: Uint8Array | ArrayBuffer | Buffer): Uint8Array
    const snappyjs: { compress: typeof compress; uncompress: typeof uncompress }
    export default snappyjs
}

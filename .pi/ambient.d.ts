// Ambient stubs so editors don't red-flag pi's peer deps or Node built-ins.
// Pi provides these at runtime via jiti — the extension runs without any
// `npm install`. Type safety inside the extension falls back to `any`.

declare module "@mariozechner/pi-coding-agent" {
    export type ExtensionAPI = any;
    export type ExtensionContext = any;
}

declare module "typebox" {
    export const Type: any;
    export type TSchema = any;
}

declare module "node:child_process" {
    export const spawn: any;
    export type ChildProcess = any;
}

declare const process: { env: Record<string, string | undefined> };
declare function setTimeout(handler: () => void, timeout: number): unknown;
declare function clearTimeout(handle: unknown): void;

interface AbortSignal {
    readonly aborted: boolean;
    addEventListener(type: "abort", listener: () => void, options?: { once?: boolean }): void;
    removeEventListener(type: "abort", listener: () => void): void;
}

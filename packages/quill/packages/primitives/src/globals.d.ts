// Unblocks vite-plugin-dts under TS 6.0. Without these declarations the
// dts emit aborts before producing dist/index.d.ts and the failure cascades
// up through quill-components, quill-blocks, and @posthog/quill itself.

// TS2882: side-effect `.css` imports require a module declaration.
declare module '*.css'

// TS2591: scroll-area.tsx has a dev-mode `typeof process` guard, and the
// package has no @types/node, so declare the minimal shape it uses.
declare const process:
    | {
          env?: {
              NODE_ENV?: string
          }
      }
    | undefined

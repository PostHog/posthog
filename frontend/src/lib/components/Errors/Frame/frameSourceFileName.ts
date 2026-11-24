/**
 * The repository file name a frame's source path points to. Bundlers keep module queries in source map paths
 * (`order.tsx?route-chunk=clientAction`, `select.vue?821e`), but the file in the repository has none.
 */
export function frameSourceFileName(source: string): string | undefined {
    return source.split(/[?#]/, 1)[0].split('/').pop() || undefined
}

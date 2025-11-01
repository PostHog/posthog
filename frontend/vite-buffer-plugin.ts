import { Plugin } from 'vite'

/**
 * Simple Vite plugin to inject Buffer globally to fix polyfill issues
 */
export function bufferInjectPlugin(): Plugin {
    return {
        name: 'posthog-buffer-inject',
        config() {
            return {
                define: {
                    global: 'globalThis',
                },
            }
        },
        transformIndexHtml: {
            enforce: 'pre',
            transform(html) {
                // Inject Buffer polyfill at the very beginning
                return html.replace(
                    '<head>',
                    `<head>
<script>
  // Inject Buffer polyfill globally
  import { Buffer } from 'buffer';
  window.Buffer = Buffer;
  globalThis.Buffer = Buffer;
</script>`
                )
            },
        },
    }
}
